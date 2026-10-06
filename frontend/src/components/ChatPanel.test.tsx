import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatPanel from "./ChatPanel";
import type { ChatMessage } from "@/lib/types";

const msgs: ChatMessage[] = [
  { id: "1", role: "user", content: "buy 2 AAPL and add PYPL", created_at: "", actions: null },
  {
    id: "2",
    role: "assistant",
    content: "Placing a buy order for 2 AAPL.",
    created_at: "",
    actions: {
      trades: [
        { status: "executed", ticker: "AAPL", side: "buy", quantity: 2, price: 190.5 },
        { status: "failed", ticker: "TSLA", side: "sell", quantity: 5, error: "insufficient_shares", detail: "You hold 0 TSLA" },
      ],
      watchlist_changes: [{ ticker: "PYPL", action: "add", status: "added" }],
      error: null,
    },
  },
];

describe("ChatPanel", () => {
  it("renders messages with roles and action chips with statuses", () => {
    render(<ChatPanel messages={msgs} loading={false} onSend={() => {}} collapsed={false} onToggle={() => {}} />);
    const rendered = screen.getAllByTestId("chat-message");
    expect(rendered.map((m) => m.getAttribute("data-role"))).toEqual(["user", "assistant"]);
    const chips = screen.getAllByTestId("chat-action");
    expect(chips.map((c) => c.getAttribute("data-status"))).toEqual(["executed", "failed", "added"]);
    expect(chips[0]).toHaveTextContent("BUY 2 AAPL @ 190.50");
    expect(chips[1]).toHaveTextContent("You hold 0 TSLA");
    expect(chips[2]).toHaveTextContent("PYPL added to watchlist");
    expect(screen.queryByTestId("chat-loading")).toBeNull();
  });

  it("shows loading indicator and disables send while waiting", () => {
    render(<ChatPanel messages={[]} loading onSend={() => {}} collapsed={false} onToggle={() => {}} />);
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-send-button")).toBeDisabled();
  });

  it("sends trimmed input and clears it", () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} loading={false} onSend={onSend} collapsed={false} onToggle={() => {}} />);
    const input = screen.getByTestId("chat-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  hello  " } });
    fireEvent.click(screen.getByTestId("chat-send-button"));
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(input.value).toBe("");
  });

  it("shows LLM error note without action chips", () => {
    const m: ChatMessage = { id: "3", role: "assistant", content: "Sorry", created_at: "", actions: { trades: [], watchlist_changes: [], error: "llm_unavailable" } };
    render(<ChatPanel messages={[m]} loading={false} onSend={() => {}} collapsed={false} onToggle={() => {}} />);
    expect(screen.queryAllByTestId("chat-action")).toHaveLength(0);
    expect(screen.getByText(/llm_unavailable/)).toBeInTheDocument();
  });
});
