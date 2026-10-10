"""Offline party-finder preview: synthetic parties from the shared contract, loopback only.

Usage: python tools/preview_party.py [browse|joined|full|leader]
No authentication, Hypixel or Mojang calls. Actions return canned states.
"""

import copy
import json
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preview_skin import CARD, DIST, Preview  # noqa: E402

CONTRACT = json.loads((DIST.parents[1] / "contracts/party-v1.json").read_text(encoding="utf-8"))
SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "browse"


def listings():
    base = CONTRACT["listings"]["parties"][0]
    rows = []
    variants = [
        ("Lumen", [True, True, False, True, True], {"catacombs": 45, "s_plus_ms": 360000}, 305000),
        ("Noctis", [False, False, True, True, False], base["rules"]["shared"], 324500),
        ("Corvid", [False, False, False, False, True], {"catacombs": 40}, 352000),
        (
            "Vespa",
            [False, True, False, True, False],
            {"catacombs": 55, "magical_power": 1500},
            299500,
        ),
        (
            "Talon",
            [True, True, True, True, False],
            {"catacombs": 50, "terminals_ms": 42000},
            322500,
        ),
    ]
    for index, (leader, filled, shared, average) in enumerate(variants):
        row = copy.deepcopy(base)
        row["id"] = f"party{index:07d}"
        row["leader"] = leader
        if leader != "Noctis":
            row["leader_uuid"] = f"{index + 100:032x}"
        row["created_at"] = 1060.0 - index * 180
        row["slots"] = [
            {"role": slot["role"], "filled": value}
            for slot, value in zip(base["slots"], filled, strict=True)
        ]
        row["rules"] = {**base["rules"], "shared": shared}
        if leader != "Noctis":
            row["rules"]["per_class"] = {}
        row["team"] = {"catacombs_avg": 50 + index, "s_plus_ms_avg": average}
        rows.append(row)
    return rows


def state(kind):
    joined = copy.deepcopy(CONTRACT["state"])
    if kind == "browse":
        return {**joined, "notices": [], "party": None}
    if kind == "leader":
        return copy.deepcopy(CONTRACT["leader_state"])
    if kind == "full":
        party = joined["party"]
        party["slots"] = [{**slot, "filled": True} for slot in party["slots"]]
        names = ["Kestrel", "Orrin", None, None, "Quill"]
        for index, name in enumerate(names):
            if name:
                party["members"].append(
                    {
                        **party["members"][1],
                        "slot": index,
                        "name": name,
                        "leader": False,
                        "uuid": f"{index:032x}",
                    }
                )
        party["members"].sort(key=lambda member: member["slot"])
        party["full_since"] = joined["server_time"] - 48
        party["join_deadline"] = party["full_since"] + 300
        party["joined"] = [True, True, False, True, False]
    return joined


class PartyPreview(Preview):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/v1/party/listings":
            return self.json({"version": 1, "floor": "M7", "parties": listings()})
        if path.startswith("/api/v1/party/listings/"):
            return self.json(CONTRACT["detail"])
        if path.startswith("/api/v1/party/player-card/"):
            uuid = path.rsplit("/", 1)[-1]
            names = {row["leader_uuid"]: row["leader"] for row in listings()}
            names.update(
                {member["uuid"]: member["name"] for member in CONTRACT["detail"]["members"]}
            )
            if uuid not in names:
                return self.send_error(404)
            card = json.loads(CARD.read_text(encoding="utf-8"))
            return self.json({**card, "user": {"uuid": uuid, "name": names[uuid]}})
        if path in ("/party-finder/",):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/v1/party/state":
            if "known" in body:
                # Only ever echo a number, never request text, even on this loopback harness.
                known = body["known"]
                if not isinstance(known, int) or isinstance(known, bool):
                    return self.send_error(400)
                time.sleep(20)  # held like the real server, then unchanged
                return self.json({"version": 1, "state_version": int(known), "unchanged": True})
            return self.json(state(SCENARIO))
        replies = {
            "/api/v1/party/reserve": "joined",
            "/api/v1/party/look": "joined",
            "/api/v1/party/publish": "leader",
            "/api/v1/party/leave": "browse",
            "/api/v1/party/stop-looking": "browse",
            "/api/v1/party/unlist": "browse",
        }
        if path in replies:
            return self.json(state(replies[path]))
        return self.json(state(SCENARIO))

    def json(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if not (DIST / "index.html").is_file():
        raise SystemExit("Run npm run build first.")
    print(f"Synthetic party preview ({SCENARIO}): http://127.0.0.1:8770/party-finder", flush=True)
    with ThreadingHTTPServer(("127.0.0.1", 8770), PartyPreview) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
