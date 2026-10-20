import { render, screen } from "@testing-library/react";
import { LineChart } from "./charts";

it.each([[100, 0, -50], [-100, -25], [0, 0], []])(
  "keeps signed sales and return points inside the visible chart: %j",
  (...values) => {
    const points = values.map((value, i) => ({ key: String(i), label: String(i), value }));
    render(<LineChart points={points} label="حركة المبيعات" height={210} />);
    const chart = screen.getByRole("img", { name: "حركة المبيعات" });
    const circles = [...chart.querySelectorAll("circle")];
    expect(circles).toHaveLength(values.length);
    for (const circle of circles) {
      expect(Number(circle.getAttribute("cy"))).toBeGreaterThanOrEqual(14);
      expect(Number(circle.getAttribute("cy"))).toBeLessThanOrEqual(184);
    }
    expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
    if (values[0] === 100) {
      expect(Number(circles[0]?.getAttribute("cy"))).toBeLessThan(Number(circles[1]?.getAttribute("cy")));
      expect(Number(circles[1]?.getAttribute("cy"))).toBeLessThan(Number(circles[2]?.getAttribute("cy")));
    }
  },
);
