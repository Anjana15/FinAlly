import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Watchlist from "./Watchlist";
import type { Quote } from "@/lib/types";

const quote = (ticker: string, price: number, change_percent: number) => ({ ticker, price, change_percent } as Quote);

describe("Watchlist", () => {
  it("renders rows, prices, flash class and remove buttons with stable testids", () => {
    render(
      <Watchlist
        tickers={["AAPL", "MSFT"]}
        quotes={{ AAPL: quote("AAPL", 191.2, 0.63) }}
        fallbackQuotes={{ MSFT: quote("MSFT", 400, -1.2) }}
        history={{}}
        flashes={{ AAPL: { dir: "up", seq: 1 } }}
        selected="AAPL"
        onSelect={() => {}}
        onAdd={async () => null}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("price-AAPL")).toHaveTextContent("191.20");
    expect(screen.getByTestId("price-AAPL")).toHaveClass("flash-up");
    expect(screen.getByTestId("price-MSFT")).toHaveTextContent("400.00");
    expect(screen.getByTestId("price-MSFT")).not.toHaveClass("flash-up");
    expect(screen.getByTestId("watchlist-remove-MSFT")).toBeInTheDocument();
    expect(screen.getByTestId("watchlist-row-MSFT")).toHaveTextContent("-1.20%");
  });
});
