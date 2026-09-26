import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import contract from "../../contracts/party-v1.json";
import { PartyWorkspace } from "./PartyFinder";
import { PartyForm } from "./PartyLead";
import type { Listing, PartyState } from "./partyApi";
import { chime } from "./sound";
import cardFixture from "../../contracts/player-card-v1.json";

vi.mock("./sound", () => ({ chime: vi.fn(), unlockSound: vi.fn() }));

const joined = contract.state as unknown as PartyState;
const leading = contract.leader_state as unknown as PartyState;
const listing = contract.listings.parties[0] as unknown as Listing;
const idle: PartyState = { ...joined, notices: [], party: null };

type Handler = (body: Record<string, unknown> | undefined) => unknown;

function mockApi(routes: Record<string, Handler>) {
  const calls: { path: string; body?: Record<string, unknown> }[] = [];
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    const path = url.replace(/^\/api\/v1\//, "").split("?")[0]!;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ path, body });
    // Held state requests (with a known version) wait until the test ends.
    if (path === "party/state" && body?.known !== undefined)
      return new Promise<Response>(() => {});
    const handler = routes[path];
    const value = handler ? handler(body) : { authenticated: false };
    return Promise.resolve(new Response(JSON.stringify(value)));
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

function listings(parties: Listing[]) {
  return () => ({ version: 1, floor: "M7", parties });
}

beforeEach(() => {
  vi.mocked(chime).mockClear();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([null, "Mage"])(
  "reserves any eligible class with %s selected for matching",
  async (selection) => {
    const calls = mockApi({
      "party/state": () => idle,
      "party/listings": listings([listing]),
      "party/reserve": () => joined,
      [`party/listings/${listing.id}`]: () => contract.detail,
    });
    render(<PartyWorkspace />);
    await screen.findByRole("button", { name: "Choose slot" });
    if (selection)
      fireEvent.click(screen.getByRole("button", { name: selection }));
    fireEvent.click(screen.getByRole("button", { name: "Choose slot" }));
    const reserve = await screen.findByRole("button", {
      name: "Reserve Tank in Noctis’s party",
    });
    expect(screen.getByText("Open to you · 1")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Roster" }).textContent).toContain(
      "Tank, open, you qualify",
    );
    fireEvent.click(reserve);
    expect(
      await screen.findByRole("heading", {
        name: "Healer slot held in Noctis’s party",
      }),
    ).toBeTruthy();
    expect(calls.find((call) => call.path === "party/reserve")?.body).toEqual({
      party_id: listing.id,
      role: "tank",
    });
  },
);

it("defaults fresh browsing to M7 and puts it first", async () => {
  mockApi({ "party/state": () => idle, "party/listings": listings([]) });
  render(<PartyWorkspace />);
  const floors = await screen.findByRole("group", { name: "Floor" });
  const buttons = within(floors).getAllByRole("button");
  expect(buttons[0]!.textContent).toBe("M7");
  expect(buttons[0]!.getAttribute("aria-pressed")).toBe("true");
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([url]) => url === "/api/v1/party/listings?floor=M7"),
    ).toBe(true),
  );
});

it("opens the listing leader's card without expanding or reserving the party", async () => {
  const user = { uuid: listing.leader_uuid!, name: listing.leader };
  const calls = mockApi({
    "party/state": () => idle,
    "party/listings": listings([listing]),
    [`party/player-card/${user.uuid}`]: () => ({ ...cardFixture, user }),
  });
  render(<PartyWorkspace />);
  const name = await screen.findByRole("button", {
    name: "Noctis",
  });
  expect(calls.some((call) => call.path.includes("player-card"))).toBe(false);
  fireEvent.click(name);
  const card = await screen.findByRole("dialog", { name: "Noctis" });
  expect(await within(card).findByText("42.50")).toBeTruthy();
  expect(
    calls.some(
      (call) =>
        call.path === `party/listings/${listing.id}` ||
        call.path === "party/reserve",
    ),
  ).toBe(false);
  fireEvent.click(
    within(card).getByRole("button", { name: "Close player card" }),
  );
  expect(document.activeElement).toBe(name);
});

it("opens another member's card from the held party roster", async () => {
  const user = contract.detail.members[1]!;
  mockApi({
    "party/state": () => joined,
    [`party/player-card/${user.uuid}`]: () => ({
      ...cardFixture,
      user: { uuid: user.uuid, name: user.name },
    }),
  });
  render(<PartyWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "Noctis" }));
  expect(await screen.findByRole("dialog", { name: "Noctis" })).toBeTruthy();
  expect(await screen.findByText("42.50")).toBeTruthy();
});

it("explains why a party is out of reach instead of offering it", async () => {
  const weak = {
    ...idle,
    you: {
      ...idle.you,
      stats: { ...idle.you.stats!, magical_power: 1000 },
    },
  };
  mockApi({
    "party/state": () => weak,
    "party/listings": listings([listing]),
  });
  render(<PartyWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Tank/ }));
  const toggle = await screen.findByRole("button", { name: /Can’t join · 1/ });
  expect(screen.queryByRole("button", { name: "Reserve Tank" })).toBeNull();
  fireEvent.click(toggle);
  expect(await screen.findByText("MP ≥1,300 · you 1,000")).toBeTruthy();
});

it("starts looking with the party-average limit and marks parties it will skip", async () => {
  const placed: PartyState = {
    ...joined,
    state_version: joined.state_version + 1,
    notices: [
      {
        id: "n-placed",
        kind: "placed",
        at: 1060,
        party: listing.id,
        role: "healer",
      },
    ],
  };
  const calls = mockApi({
    "party/state": () => idle,
    "party/listings": listings([listing]),
    "party/look": () => placed,
  });
  render(<PartyWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Tank/ }));
  fireEvent.change(screen.getByLabelText("Average S+ PB ≤"), {
    target: { value: "5:00" },
  });
  expect(await screen.findByText(/Skipped · S\+ avg/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Start looking" }));
  expect(
    await screen.findByRole("heading", {
      name: "Placed in Noctis’s party as Healer",
    }),
  ).toBeTruthy();
  expect(calls.find((call) => call.path === "party/look")?.body).toEqual({
    version: 1,
    floor: "M7",
    classes: ["tank"],
    max_team_s_plus_ms: 300000,
  });
  expect(chime).toHaveBeenCalledTimes(1);
});

it("lets the leader remove and block a member", async () => {
  const calls = mockApi({
    "party/state": () => leading,
    "party/remove": () => ({
      ...leading,
      state_version: leading.state_version + 1,
    }),
  });
  render(<PartyWorkspace />);
  expect(
    await screen.findByRole("heading", { name: "Your M7 party" }),
  ).toBeTruthy();
  expect(screen.getByText("Grim")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Remove…" }));
  const choice = screen.getByRole("group", { name: "Remove Sable" });
  fireEvent.click(
    within(choice).getByRole("button", { name: "Remove and block" }),
  );
  await waitFor(() =>
    expect(calls.find((call) => call.path === "party/remove")?.body).toEqual({
      member: contract.state.you.uuid,
      block: true,
    }),
  );
});

it("publishes a party with shared and class rules and names to block", async () => {
  const calls = mockApi({
    "party/state": () => idle,
    "party/listings": listings([]),
    "party/publish": () => leading,
  });
  render(<PartyWorkspace />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Create a party" }),
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "Catacombs, every open slot" }),
    { target: { value: "50" } },
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "SS average, Healer" }),
    {
      target: { value: "14.0" },
    },
  );
  fireEvent.change(screen.getByLabelText(/Add Minecraft names/), {
    target: { value: "Grim, Tarn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Publish party" }));
  expect(
    await screen.findByRole("heading", { name: "Your M7 party" }),
  ).toBeTruthy();
  expect(calls.find((call) => call.path === "party/publish")?.body).toEqual({
    version: 1,
    floor: "M7",
    leader_class: "mage",
    roles: ["archer", "berserk", "healer", "mage", "tank"],
    allow_duplicates: false,
    rules: {
      shared: { catacombs: 50 },
      per_class: { healer: { ss_ms: 14000 } },
      exempt: [],
    },
    block_names: ["Grim", "Tarn"],
  });
});

it("refuses invalid rule values before sending anything", async () => {
  const calls = mockApi({
    "party/state": () => idle,
    "party/listings": listings([]),
  });
  render(<PartyWorkspace />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Create a party" }),
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "S+ PB, every open slot" }),
    { target: { value: "5 minutes" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Publish party" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(calls.some((call) => call.path === "party/publish")).toBe(false);
});

it("restores the server's F7 search instead of disabling the selector on M7", async () => {
  const searching = {
    ...idle,
    you: {
      ...idle.you,
      looking: { floor: "F7", classes: ["tank"], limit: null, since: 1000 },
    },
  };
  mockApi({ "party/state": () => searching, "party/listings": listings([]) });
  render(<PartyWorkspace />);
  const f7 = await screen.findByRole("button", { name: "F7" });
  expect(f7.getAttribute("aria-pressed")).toBe("true");
  expect(
    screen.getByRole("button", { name: "M7" }).getAttribute("aria-pressed"),
  ).toBe("false");
  expect(screen.getByRole("heading", { name: "Your F7 records" })).toBeTruthy();
});

it("preserves Archer rules when editing a Mage plus four Archers party", async () => {
  const duplicate = structuredClone(leading);
  duplicate.party!.slots = ["mage", "archer", "archer", "archer", "archer"].map(
    (role) => ({ role: role as "mage" | "archer", filled: role === "mage" }),
  );
  duplicate.party!.members = [
    { ...duplicate.party!.members.find((member) => member.leader)!, slot: 0 },
  ];
  duplicate.party!.rules = {
    shared: {},
    per_class: { archer: { magical_power: 1400 } },
    exempt: [],
  };
  const calls = mockApi({ "party/edit": () => duplicate });
  render(
    <PartyForm
      mode="edit"
      state={duplicate}
      floor="M7"
      busy={false}
      run={async (task) => {
        await task();
        return true;
      }}
      onDone={() => {}}
    />,
  );
  expect(
    (
      screen.getByRole("textbox", {
        name: "Magical Power, Archer",
      }) as HTMLInputElement
    ).value,
  ).toBe("1400");
  fireEvent.click(screen.getByRole("button", { name: "Save requirements" }));
  await waitFor(() =>
    expect(
      calls.find((call) => call.path === "party/edit")?.body?.rules,
    ).toEqual(duplicate.party!.rules),
  );
});
