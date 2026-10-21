import { activityLabels } from "./office";
import type { PositionedAgent } from "./office";
import type { AgentActivity } from "./types";

export interface BubbleRect {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface AgentEventBubble extends BubbleRect {
  agent: AgentActivity;
  name: string;
  label: string;
  summary: string;
  title: string;
  anchorX: number;
  anchorY: number;
}
export interface AgentEventLayout {
  bubbles: AgentEventBubble[];
  tooSmall: boolean;
}
export function recordedAgentEvent(agent: AgentActivity) {
  return (
    (Number.isSafeInteger(agent.seq) && (agent.seq ?? 0) > 0) ||
    (typeof agent.timestamp === "string" &&
      Number.isFinite(Date.parse(agent.timestamp)))
  );
}
export function eligibleAgentEvent(
  displayed: AgentActivity,
  recorded?: AgentActivity,
) {
  return (
    !!recorded &&
    recordedAgentEvent(recorded) &&
    recorded.activity !== "error" &&
    displayed.activity !== "error"
  );
}
function overlaps(a: BubbleRect, b: BubbleRect, gap = 4) {
  return (
    a.x < b.x + b.width + gap &&
    a.x + a.width + gap > b.x &&
    a.y < b.y + b.height + gap &&
    a.y + a.height + gap > b.y
  );
}
const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(value, high));

export function layoutAgentEvents(
  positioned: PositionedAgent[],
  records: AgentActivity[],
  width: number,
  height: number,
  obstacles: BubbleRect[] = [],
  grid = false,
): AgentEventLayout {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width < 140 ||
    height < 68
  )
    return { bubbles: [], tooSmall: true };
  const recorded = new Map(records.map((agent) => [agent.agent_id, agent]));
  const recordedCount = positioned.filter(({ agent }) => {
    const event = recorded.get(agent.agent_id);
    return eligibleAgentEvent(agent, event);
  }).length;
  const cardWidth =
    recordedCount > 10
      ? Math.max(110, Math.min(122, Math.floor((width - 28) / 5)))
      : Math.min(176, Math.max(122, Math.floor(width / 4.5)));
  const cardHeight = 56;
  const margin = 6;
  const avatars = positioned.map(({ role }) => ({
    x: (role.x / 1000) * width - 13,
    y: (Math.min(role.y, 594) / 650) * height - 13,
    width: 26,
    height: 26,
  }));
  const placed: AgentEventBubble[] = [];
  const ordered = [...positioned].sort(
    (a, b) => a.role.y - b.role.y || a.role.x - b.role.x,
  );
  for (const { agent: displayed, role } of ordered) {
    const agent = recorded.get(displayed.agent_id);
    if (!agent || !eligibleAgentEvent(displayed, agent)) continue;
    const anchorX = (role.x / 1000) * width;
    const anchorY = (Math.min(role.y, 594) / 650) * height;
    const desiredX = clamp(
      anchorX - cardWidth / 2,
      margin,
      width - cardWidth - margin,
    );
    const desiredY = clamp(
      anchorY - cardHeight - 24,
      margin,
      height - cardHeight - margin,
    );
    const xs = new Set(
      grid ? [] : [desiredX, margin, width - cardWidth - margin],
    );
    const ys = new Set(
      grid ? [] : [desiredY, margin, height - cardHeight - margin],
    );
    for (
      let x = margin;
      x <= width - cardWidth - margin;
      x += grid ? cardWidth + 4 : 4
    )
      xs.add(x);
    for (
      let y = margin;
      y <= height - cardHeight - margin;
      y += grid ? cardHeight + 4 : 4
    )
      ys.add(y);
    for (const previous of grid ? [] : placed) {
      xs.add(
        clamp(previous.x - cardWidth - 4, margin, width - cardWidth - margin),
      );
      xs.add(
        clamp(
          previous.x + previous.width + 4,
          margin,
          width - cardWidth - margin,
        ),
      );
      ys.add(
        clamp(
          previous.y - cardHeight - 4,
          margin,
          height - cardHeight - margin,
        ),
      );
      ys.add(
        clamp(
          previous.y + previous.height + 4,
          margin,
          height - cardHeight - margin,
        ),
      );
    }
    let best: BubbleRect | undefined;
    let score = Infinity;
    const blocked = [...placed, ...obstacles];
    for (const y of ys)
      for (const x of xs) {
        const candidate = { x, y, width: cardWidth, height: cardHeight };
        const distance =
          (x - desiredX) ** 2 +
          (y - desiredY) ** 2 * 1.3 +
          (x <= anchorX &&
          x + cardWidth >= anchorX &&
          y + cardHeight > anchorY - 18
            ? 18000
            : 0);
        if (
          distance >= score ||
          blocked.some((box) => overlaps(candidate, box)) ||
          avatars.some((box) => overlaps(candidate, box, 2))
        )
          continue;
        best = candidate;
        score = distance;
      }
    // A dense map can fragment the free space around earlier nearest choices.
    // Repack into consistent lanes rather than overlap or hide late actors.
    if (!best && !grid)
      return layoutAgentEvents(
        positioned,
        records,
        width,
        height,
        obstacles,
        true,
      );
    if (!best) return { bubbles: [], tooSmall: true };
    const label = activityLabels[agent.activity];
    const summary = agent.summary?.trim() ?? "";
    const title = `${role.name}. Last event: ${label}.${summary ? ` ${summary}` : ""}${agent.timestamp ? ` (${agent.timestamp})` : ""}`;
    placed.push({
      ...best,
      agent,
      name: role.name,
      label,
      summary,
      title,
      anchorX,
      anchorY,
    });
  }
  return { bubbles: placed, tooSmall: false };
}
