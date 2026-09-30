import {
  CLASSES,
  METRIC_ORDER,
  METRICS,
  type Floor,
  type Rules,
  type Thresholds,
} from "./partyApi";

const key = (uuid: string, floor: Floor) =>
  `mithril.party-rules.v1:${uuid}:${floor}`;
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function thresholds(value: unknown): value is Thresholds {
  return (
    object(value) &&
    Object.entries(value).every(
      ([metric, number]) =>
        METRIC_ORDER.includes(metric as keyof Thresholds) &&
        typeof number === "number" &&
        Number.isInteger(number) &&
        number >= 1 &&
        number <= METRICS[metric as keyof Thresholds].max,
    )
  );
}

export function loadPartyRules(uuid: string, floor: Floor): Rules {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(key(uuid, floor)) ?? "null",
    );
    if (object(value) && value.version === 1 && object(value.rules)) {
      const rules = value.rules;
      if (
        thresholds(rules.shared) &&
        object(rules.per_class) &&
        Object.entries(rules.per_class).every(
          ([role, limits]) =>
            CLASSES.includes(role as (typeof CLASSES)[number]) &&
            thresholds(limits),
        ) &&
        Array.isArray(rules.exempt) &&
        rules.exempt.every((role) => CLASSES.includes(role))
      ) {
        return rules as Rules;
      }
    }
  } catch {
    /* Browser storage may be unavailable. */
  }
  return { shared: {}, per_class: {}, exempt: [] };
}

export function savePartyRules(
  uuid: string,
  floor: Floor,
  rules: Rules,
): boolean {
  try {
    localStorage.setItem(
      key(uuid, floor),
      JSON.stringify({ version: 1, rules }),
    );
    return true;
  } catch {
    return false;
  }
}

export function resetPartyRules(uuid: string, floor: Floor): boolean {
  try {
    localStorage.removeItem(key(uuid, floor));
    return true;
  } catch {
    return false;
  }
}
