import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PartyChat, type ChatMessage } from "./PartyChat";

afterEach(cleanup);
const message: ChatMessage = {
  id: "1",
  text: "I’ll take blood rush.",
  at: 1_000,
  sender: { name: "TestPlayer", uuid: "0123456789abcdef0123456789abcdef" },
  source: "game",
};

it("renders an empty state and rejects blank messages", () => {
  const onSend = vi.fn();
  const { container } = render(
    <PartyChat messages={[]} connected onSend={onSend} />,
  );
  expect(screen.getByText("No messages yet")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
});

it("sends trimmed plain text once and clears the composer", async () => {
  const onSend = vi.fn();
  const { container } = render(
    <PartyChat messages={[]} connected onSend={onSend} />,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: " hello party  " },
  });
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).toHaveBeenCalledExactlyOnceWith(
    "hello party",
    expect.any(String),
  );
  await waitFor(() =>
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe(""),
  );
});

it("preserves the draft through disconnect, hiding and reconnect", () => {
  const onSend = vi.fn();
  const view = render(<PartyChat messages={[]} connected onSend={onSend} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "ready" } });
  view.rerender(<PartyChat messages={[]} connected={false} onSend={onSend} />);
  fireEvent.submit(view.container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  expect(
    (screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByRole("textbox")).toBeNull();
  view.rerender(<PartyChat messages={[]} connected onSend={onSend} />);
  fireEvent.click(screen.getByRole("button", { name: "Show" }));
  expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("ready");
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(onSend).toHaveBeenCalledExactlyOnceWith("ready", expect.any(String));
});

it("distinguishes sources and exposes player-card buttons without interpreting markup", () => {
  const { container } = render(
    <PartyChat
      messages={[
        message,
        {
          ...message,
          id: "2",
          source: "web",
          text: "<img src=x onerror=alert(1)>",
        },
        { id: "3", text: "A player joined.", at: 2_000 },
      ]}
      connected
      onSend={vi.fn()}
    />,
  );
  expect(screen.getByText("In game")).toBeTruthy();
  expect(screen.getByText("Web")).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "TestPlayer" })).toHaveLength(2);
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
});

it("marks new messages while hidden", () => {
  const view = render(
    <PartyChat messages={[message]} connected onSend={vi.fn()} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  view.rerender(
    <PartyChat
      messages={[message, { ...message, id: "2" }]}
      connected
      onSend={vi.fn()}
    />,
  );
  expect(screen.getByLabelText("New messages")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Show/ }));
  expect(screen.queryByLabelText("New messages")).toBeNull();
});

it("does not pull readers away from earlier messages", () => {
  const view = render(
    <PartyChat messages={[message]} connected onSend={vi.fn()} />,
  );
  const log = screen.getByRole("log");
  Object.defineProperties(log, {
    scrollHeight: { configurable: true, value: 1000 },
    clientHeight: { configurable: true, value: 300 },
  });
  log.scrollTop = 100;
  fireEvent.scroll(log);
  view.rerender(
    <PartyChat
      messages={[message, { ...message, id: "2" }]}
      connected
      onSend={vi.fn()}
    />,
  );
  expect(log.scrollTop).toBe(100);
  fireEvent.click(screen.getByRole("button", { name: "New messages ↓" }));
  expect(log.scrollTop).toBe(1000);
});

it.each([255, 256, 257])(
  "bounds outgoing text at 256 characters (%s)",
  (size) => {
    const onSend = vi.fn();
    const { container } = render(
      <PartyChat messages={[]} connected onSend={onSend} />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "a".repeat(size) },
    });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).toHaveBeenCalledTimes(size <= 256 ? 1 : 0);
  },
);

it("keeps a failed draft and reuses its id when retried", async () => {
  const onSend = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(undefined);
  render(<PartyChat messages={[]} connected onSend={onSend} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "ready" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("ready");
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() =>
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe(""),
  );
  expect(onSend.mock.calls[0]).toEqual(onSend.mock.calls[1]);
});

it("allows only one outstanding send and guards composition Enter", async () => {
  let finish!: () => void;
  const onSend = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<PartyChat messages={[]} connected onSend={onSend} />);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "ready" } });
  expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true })).toBe(
    false,
  );
  fireEvent.submit(view.container.querySelector("form")!);
  fireEvent.submit(view.container.querySelector("form")!);
  expect(onSend).toHaveBeenCalledTimes(1);
  expect((input as HTMLInputElement).readOnly).toBe(true);
  finish();
  await waitFor(() => expect((input as HTMLInputElement).value).toBe(""));
});
