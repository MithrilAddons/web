import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import contract from "../../contracts/party-v1.json";
import { partyApi, type PartyState, usePartyState } from "./partyApi";

const original = contract.state as unknown as PartyState;
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("accepts a new generation after restart instead of polling the old party forever", async () => {
  const restarted = {
    ...original,
    state_id: "restarted:1",
    state_version: 1,
    party: null,
  };
  const poll = vi
    .spyOn(partyApi, "state")
    .mockResolvedValueOnce(original)
    .mockResolvedValueOnce(restarted)
    .mockImplementation(() => new Promise(() => {}));
  const { result } = renderHook(usePartyState);
  await waitFor(() => expect(result.current.state).toEqual(restarted));
  expect(poll).toHaveBeenCalledTimes(2);
  // A late action response from the old process must not resurrect the old party.
  act(() => result.current.apply(original));
  expect(result.current.state).toEqual(restarted);
});

it("still ignores out-of-order revisions within the same generation", async () => {
  vi.spyOn(partyApi, "state")
    .mockResolvedValueOnce(original)
    .mockImplementation(() => new Promise(() => {}));
  const { result } = renderHook(usePartyState);
  await waitFor(() => expect(result.current.state).toEqual(original));
  act(() =>
    result.current.apply({ ...original, state_version: 0, party: null }),
  );
  expect(result.current.state).toEqual(original);
});
