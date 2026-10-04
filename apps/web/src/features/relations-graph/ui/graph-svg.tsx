import { cn } from "@compliancewatch/ui";
import { humanise } from "@/shared/lib/humanise";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import { NODE_HEIGHT, NODE_WIDTH, shorten, type GraphLayout } from "../model/graph";

export interface GraphSvgProps {
  layout: GraphLayout;
}

/**
 * The graph drawn: a box per version (its rule key, number and status) or entity (its type and
 * name), an arrow per relation labelled with its kind. It is a picture only, hidden from
 * assistive technology: the table beside it holds the same relations with their links.
 */
export function GraphSvg({ layout }: GraphSvgProps) {
  return (
    <div
      className="overflow-x-auto rounded-md border border-line bg-surface"
      data-slot="graph-picture"
    >
      <svg
        aria-hidden="true"
        focusable="false"
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="block"
      >
        <defs>
          <marker
            id="graph-arrow"
            viewBox="0 0 10 10"
            refX="10"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-fg-muted" />
          </marker>
        </defs>
        {layout.edges.map((edge) => (
          <g key={edge.relationId} data-edge={edge.relation}>
            <path
              d={edge.path}
              fill="none"
              strokeWidth={1.5}
              markerEnd="url(#graph-arrow)"
              className="stroke-fg-muted"
            />
            <text
              x={edge.labelX}
              y={edge.labelY - 6}
              textAnchor="middle"
              className="fill-fg text-[11px]"
            >
              {humanise(edge.relation)}
            </text>
          </g>
        ))}
        {layout.nodes.map((node) => (
          <g key={node.key} data-node={node.key} data-kind={node.kind}>
            <rect
              x={node.x}
              y={node.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={8}
              strokeWidth={node.start ? 2.5 : 1}
              className={cn(
                node.kind === "entity" ? "fill-surface" : "fill-surface-raised",
                node.start ? "stroke-primary" : "stroke-line-strong",
              )}
              strokeDasharray={node.kind === "entity" ? "4 3" : undefined}
            />
            <text x={node.x + 12} y={node.y + 23} className="fill-fg text-[13px] font-medium">
              {shorten(node.label)}
            </text>
            <text x={node.x + 12} y={node.y + 42} className="fill-fg-muted text-[11px]">
              {node.status === null
                ? shorten(node.detail ?? "")
                : shorten(ruleVersionStatusLabel(node.status))}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
