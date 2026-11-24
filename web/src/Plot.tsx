import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import type { Data, Layout, PlotMouseEvent, PlotRelayoutEvent } from "plotly.js";

// Plotly supports autoexpand; its TypeScript Margin type omits the property.
const plotMargin = {
  l: 72,
  r: 20,
  t: 20,
  b: 56,
  autoexpand: false
};

interface Props {
  data: Data[];
  layout?: Partial<Layout>;
  onClick?: (event: PlotMouseEvent) => void;
  onZoom?: (event: PlotRelayoutEvent) => void;
}

/**
 * Own one Plotly instance and serialize drawing, resizing, and cleanup
 * operations.
 */
export function Plot({ data, layout, onClick, onZoom }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  // Event listeners stay attached once, but call the handlers from the latest
  // render.
  const callbacks = useRef({
    onClick,
    onZoom
  });
  const alive = useRef(false);
  callbacks.current = {
    onClick,
    onZoom
  };

  // Create the plot once; subsequent renders join the same operation queue
  // below.
  useEffect(() => {
    const node = element.current!;
    alive.current = true;
    // Fast Refresh reuses this node: finish the previous cleanup before creating
    // its replacement, so an old purge cannot erase the newly rendered plot.
    queue.current = queue.current
      .then(() => {
        if (!alive.current) {
          return;
        }
        return Plotly.newPlot(
          node,
          [],
          {},
          {
            responsive: true,
            displaylogo: false
          }
        );
      })
      .then(() => {
        if (!alive.current) {
          return;
        }
        const plot = node as unknown as Plotly.PlotlyHTMLElement;
        plot.on("plotly_click", (event) => callbacks.current.onClick?.(event));
        plot.on("plotly_relayout", (event) => callbacks.current.onZoom?.(event));
      });
    const observer = new ResizeObserver(() => {
      queue.current = queue.current.then(() => {
        // Setup/Explore keeps hidden views mounted; Plotly cannot resize a
        // zero-size plot.
        if (
          alive.current &&
          node.isConnected &&
          node.clientWidth > 0 &&
          node.clientHeight > 0
        ) {
          return Plotly.Plots.resize(node);
        }
      });
    });
    observer.observe(node);
    return () => {
      alive.current = false;
      observer.disconnect();
      // Let pending operations finish before destroying their Plotly instance.
      queue.current = queue.current.then(() => Plotly.purge(node));
    };
  }, []);

  // Wait for initialization or earlier updates before applying new data and
  // layout.
  useEffect(() => {
    queue.current = queue.current.then(() => {
      if (!alive.current) {
        return;
      }
      return Plotly.react(element.current!, data, {
        paper_bgcolor: "#fff",
        plot_bgcolor: "#fff",
        font: {
          family: "Inter, system-ui",
          size: 12,
          color: "#000000"
        },
        margin: plotMargin,
        ...layout,
        // Shared fixed margins keep the stacked retention-time axes aligned.
        xaxis: {
          showgrid: false,
          zeroline: false,
          showline: true,
          color: "#000000",
          linecolor: "#000000",
          tickcolor: "#000000",
          automargin: false,
          ...layout?.xaxis
        },
        yaxis: {
          showgrid: false,
          zeroline: false,
          showline: true,
          color: "#000000",
          linecolor: "#000000",
          tickcolor: "#000000",
          automargin: false,
          ...layout?.yaxis
        }
      });
    });
  }, [data, layout]);

  return (
    <div
      className="plot"
      ref={element}
    />
  );
}
