import { useEffect, useRef, useState } from "react";
import {
  activeActivities,
  activityLabels,
  handoffEndpoints,
  officeRoster,
  specialistsPerPage,
  integrationsPerPage,
} from "./office";
import type { PositionedAgent } from "./office";
import type { ActivityEvent, AgentActivity } from "./types";

const W = 1000,
  H = 650;
function rect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  fill: string,
) {
  ctx.fillStyle = fill;
  ctx.fillRect(x, y, w, h);
}
function label(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  color = "#4b4a3e",
  size = 11,
  align: CanvasTextAlign = "center",
  maxWidth?: number,
  preserveEnd = false,
) {
  ctx.fillStyle = color;
  ctx.font = `600 ${size}px ui-monospace, SFMono-Regular, monospace`;
  ctx.textAlign = align;
  let display = text;
  if (maxWidth !== undefined && ctx.measureText(text).width > maxWidth) {
    const characters = Array.from(text);
    if (preserveEnd) {
      let left = Math.ceil(characters.length / 2),
        right = Math.floor(characters.length / 2);
      const shortened = () =>
        `${characters.slice(0, left).join("")}…${right ? characters.slice(-right).join("") : ""}`;
      while (left + right && ctx.measureText(shortened()).width > maxWidth) {
        if (left > right) left--;
        else right--;
      }
      display = shortened();
    } else {
      while (
        characters.length &&
        ctx.measureText(`${characters.join("")}…`).width > maxWidth
      ) {
        characters.pop();
      }
      display = `${characters.join("")}…`;
    }
  }
  ctx.fillText(display, x, y);
}
function floor(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  base: string,
  line: string,
) {
  rect(ctx, x, y, w, h, base);
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  for (let xx = x; xx <= x + w; xx += 25) {
    ctx.beginPath();
    ctx.moveTo(xx, y);
    ctx.lineTo(xx, y + h);
    ctx.stroke();
  }
  for (let yy = y; yy <= y + h; yy += 25) {
    ctx.beginPath();
    ctx.moveTo(x, yy);
    ctx.lineTo(x + w, yy);
    ctx.stroke();
  }
}
function plant(ctx: CanvasRenderingContext2D, x: number, y: number) {
  rect(ctx, x - 7, y + 6, 14, 13, "#a97354");
  rect(ctx, x - 9, y + 4, 18, 4, "#c3936b");
  rect(ctx, x - 2, y - 11, 4, 19, "#5b7651");
  rect(ctx, x - 13, y - 12, 12, 10, "#75935d");
  rect(ctx, x + 1, y - 17, 11, 12, "#819d65");
  rect(ctx, x - 8, y - 23, 10, 12, "#8ea86f");
}
function chair(ctx: CanvasRenderingContext2D, x: number, y: number) {
  rect(ctx, x - 10, y - 5, 20, 17, "#65736b");
  rect(ctx, x - 12, y + 6, 24, 7, "#829085");
  rect(ctx, x - 8, y + 13, 3, 5, "#45554b");
  rect(ctx, x + 5, y + 13, 3, 5, "#45554b");
}
function desk(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color = "#a7c2ab",
) {
  chair(ctx, x, y + 8);
  rect(ctx, x - 38, y - 46, 76, 34, "#9b7958");
  rect(ctx, x - 38, y - 50, 76, 32, "#d0b38a");
  rect(ctx, x - 34, y - 49, 68, 2, "#e1caa2");
  rect(ctx, x - 19, y - 47, 38, 23, "#455851");
  rect(ctx, x - 16, y - 44, 32, 17, color);
  rect(ctx, x - 13, y - 41, 15, 2, "#718c77");
  rect(ctx, x - 13, y - 36, 23, 2, "#839c82");
  rect(ctx, x - 4, y - 24, 8, 4, "#495b51");
  rect(ctx, x - 12, y - 19, 24, 3, "#e0d8be");
  rect(ctx, x + 26, y - 34, 5, 7, "#f7eac9");
}
const sprite = [
  "    hhhh    ",
  "   hhhhhh   ",
  "   hssssh   ",
  "   sssssss  ",
  "    ssss    ",
  "   cccccc   ",
  "  cccccccc  ",
  "  sccccccs  ",
  "  sccccccs  ",
  "   cccccc   ",
  "   dddddd   ",
  "   dd  dd   ",
  "   dd  dd   ",
  "  bbb  bbb  ",
];
function character(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
  index: number,
) {
  const palette: Record<string, string> = {
    h: ["#584033", "#39463c", "#704b32", "#423a48"][index % 4],
    s: ["#e0b98d", "#ba8b66", "#e9c5a5", "#d2a276"][index % 4],
    c: color,
    d: "#4e5a61",
    b: "#36423e",
  };
  const size = 2;
  sprite.forEach((row, yy) =>
    [...row].forEach((pixel, xx) => {
      if (pixel !== " ")
        rect(
          ctx,
          x + (xx - 6) * size,
          y + (yy - 8) * size,
          size,
          size,
          palette[pixel],
        );
    }),
  );
}
function badgeColor(activity: string) {
  return activity === "error"
    ? "#e0987b"
    : activity === "completed"
      ? "#a7d38e"
      : activity === "waiting"
        ? "#d6bd7c"
        : activeActivities.has(activity as AgentActivity["activity"])
          ? "#a7dc9a"
          : "#9aab9c";
}
function draw(
  ctx: CanvasRenderingContext2D,
  positioned: PositionedAgent[],
  selected: string,
  events: ActivityEvent[],
  time: number,
  reduced: boolean,
) {
  rect(ctx, 0, 0, W, H, "#c3c8b0");
  // The warm, fixed office is drawn from original geometric pixel assets.
  floor(ctx, 30, 30, 940, 590, "#d9c7a4", "#ccb991");
  floor(ctx, 323, 30, 354, 182, "#c8c0d2", "#beb5ca");
  floor(ctx, 30, 240, 335, 268, "#c1cdb0", "#b3c19f");
  floor(ctx, 635, 240, 335, 268, "#b9cad1", "#abbfc7");
  floor(ctx, 385, 258, 230, 222, "#ddd1ad", "#d3c59c");
  rect(ctx, 30, 23, 940, 16, "#808d78");
  rect(ctx, 30, 39, 940, 6, "#a2ad92");
  rect(ctx, 23, 23, 12, 604, "#87927c");
  rect(ctx, 965, 23, 12, 604, "#87927c");
  rect(ctx, 23, 620, 954, 12, "#87927c");
  [
    [320, 30, 8, 167],
    [672, 30, 8, 167],
    [320, 206, 120, 9],
    [560, 206, 120, 9],
    [30, 232, 310, 9],
    [660, 232, 310, 9],
    [365, 240, 8, 70],
    [365, 395, 8, 114],
    [627, 240, 8, 70],
    [627, 395, 8, 114],
  ].forEach(([x, y, w, h]) => {
    rect(ctx, x, y, w, h, "#93a18c");
    rect(ctx, x, y, w, 3, "#b4bea3");
  });
  // North windows, books, a quiet reading nook and entryway furniture.
  for (const x of [80, 210, 733, 863]) {
    rect(ctx, x, 45, 64, 37, "#92a89b");
    rect(ctx, x + 4, 49, 56, 29, "#c8ded3");
    rect(ctx, x + 30, 49, 4, 29, "#edf0d6");
    rect(ctx, x + 4, 62, 56, 3, "#edf0d6");
  }
  rect(ctx, 72, 130, 204, 47, "#a0886b");
  rect(ctx, 76, 122, 196, 43, "#bba88b");
  for (let i = 0; i < 14; i++) {
    rect(
      ctx,
      81 + i * 13,
      128 + (i % 3) * 3,
      8,
      25 - (i % 3) * 3,
      ["#849a7b", "#b3896d", "#9a92a4", "#bcb087"][i % 4],
    );
  }
  label(ctx, "KNOWLEDGE LIBRARY", 174, 196, "#6c6e59", 9);
  label(ctx, "TOOLS R&D", 805, 196, "#716b79", 9);
  plant(ctx, 60, 208);
  plant(ctx, 940, 206);
  plant(ctx, 345, 75);
  plant(ctx, 650, 75);
  plant(ctx, 61, 472);
  plant(ctx, 941, 473);
  rect(ctx, 444, 53, 112, 16, "#8b8a92");
  label(ctx, "S P O C", 500, 65, "#ece7df", 11);
  label(ctx, "EXECUTIVE", 500, 192, "#716b79", 10);
  label(ctx, "RESEARCH", 198, 489, "#576d53", 11);
  label(ctx, "ENGINEERING", 803, 489, "#536f7a", 11);
  label(ctx, "QUALITY GATES", 500, 287, "#8b7953", 9);
  rect(ctx, 426, 422, 148, 22, "#d1bc91");
  rect(ctx, 432, 427, 136, 10, "#e5d3b0");
  label(ctx, "HUMAN REVIEW", 500, 458, "#8b7953", 9);
  label(ctx, "INTEGRATIONS", 225, 625, "#847b63", 9);
  label(ctx, "ENGINEERING SPECIALISTS", 790, 625, "#536f7a", 9);
  rect(ctx, 451, 530, 98, 38, "#b6b393");
  rect(ctx, 455, 526, 90, 37, "#d2ceb0");
  label(ctx, "↟", 500, 550, "#829276", 24);
  positioned.forEach(({ agent, role }, i) => {
    const external = role.kind === "external";
    const x = role.x,
      y = Math.min(role.y, 594);
    if (role.kind !== "internal") desk(ctx, x, y, role.color);
    const active = activeActivities.has(agent.activity);
    const selectedAgent = selected === agent.agent_id;
    if (selectedAgent) {
      ctx.strokeStyle = "#526d49";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(x - 25, y - 25, 50, 47);
      ctx.setLineDash([]);
    }
    rect(ctx, x - 11, y + 13, 23, 4, "#979e82");
    const bob = active && !reduced ? Math.floor(time / 500) % 2 : 0;
    character(ctx, x, y - bob, role.color, i);
    rect(ctx, x + 13, y - 15, 7, 7, badgeColor(agent.activity));
    if (role.kind === "fixed" && agent.agent_id.endsWith("_gatekeeper")) {
      label(
        ctx,
        agent.agent_id.startsWith("research") ? "Research" : "Engineering",
        x,
        y + 34,
        "#435047",
        10,
      );
      label(ctx, "reviewer", x, y + 46, "#59634f", 9);
    } else {
      label(
        ctx,
        agent.display_name ?? agent.name ?? role.name,
        x,
        y + 35,
        "#435047",
        external ? 11 : 10,
        "center",
        role.kind === "specialist" ? 92 : external ? 112 : 140,
        role.kind === "specialist",
      );
    }
    if (active || agent.activity === "error" || agent.activity === "waiting") {
      const text = activityLabels[agent.activity];
      const width = ctx.measureText(text).width + 14;
      rect(
        ctx,
        x - width / 2,
        y - 75,
        width,
        18,
        agent.activity === "error" ? "#eed0bb" : "#f5f0d9",
      );
      label(ctx, text, x, y - 62, "#4f6250", 9);
    }
  });
  // Handoffs are drawn only when an actual event identifies both agents.
  events.slice(0, 8).forEach((event) => {
    const endpoints = handoffEndpoints(event, positioned);
    if (!endpoints) return;
    const age = Date.now() - Date.parse(event.timestamp);
    if (age < 0 || age > 1800) return;
    const { from, to } = endpoints;
    ctx.strokeStyle = "#7d9669";
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.setLineDash([]);
    const t = reduced ? 0.5 : age / 1800;
    rect(
      ctx,
      from.x + (to.x - from.x) * t - 3,
      from.y + (to.y - from.y) * t - 3,
      6,
      6,
      "#fbf2cf",
    );
  });
}
export function OfficeCanvas({
  agents,
  selected,
  onSelect,
  events,
}: {
  agents: AgentActivity[];
  selected: string;
  onSelect: (id: string) => void;
  events: ActivityEvent[];
}) {
  const [specialistPage, setSpecialistPage] = useState(0);
  const [integrationPage, setIntegrationPage] = useState(0);
  const roster = officeRoster(agents, specialistPage, integrationPage);
  const specialistIds = roster.specialists
    .map((agent) => agent.agent_id)
    .join("|");
  const integrationIds = roster.integrations
    .map((agent) => agent.agent_id)
    .join("|");
  useEffect(() => {
    const index = roster.specialists.findIndex(
      (agent) => agent.agent_id === selected,
    );
    if (index >= 0) setSpecialistPage(Math.floor(index / specialistsPerPage));
  }, [selected, specialistIds]);
  useEffect(() => {
    const index = roster.integrations.findIndex(
      (agent) => agent.agent_id === selected,
    );
    if (index >= 0) setIntegrationPage(Math.floor(index / integrationsPerPage));
  }, [selected, integrationIds]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(media.matches);
    const changed = () => setReduced(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const ctx = node.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let previous = 0;
    function render(time = 0) {
      if (!node || !ctx) return;
      const ratio = window.devicePixelRatio || 1;
      const width = node.clientWidth;
      const height = node.clientHeight;
      if (!width || !height) return;
      if (
        node.width !== Math.round(width * ratio) ||
        node.height !== Math.round(height * ratio)
      ) {
        node.width = Math.round(width * ratio);
        node.height = Math.round(height * ratio);
      }
      ctx.setTransform(node.width / W, 0, 0, node.height / H, 0, 0);
      ctx.imageSmoothingEnabled = false;
      draw(ctx, roster.positioned, selected, events, time, reduced);
    }
    render();
    const observer = new ResizeObserver(() => render());
    observer.observe(node);
    function animate(time: number) {
      if (time - previous > 140) {
        render(time);
        previous = time;
      }
      frame = requestAnimationFrame(animate);
    }
    if (!reduced) frame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [
    agents,
    selected,
    events,
    reduced,
    roster.specialistPage,
    roster.integrationPage,
  ]);
  return (
    <div className="office-canvas">
      <canvas
        ref={canvas}
        role="img"
        aria-label="Top-down office: executive room north, Tools R&D northeast, research west, engineering east, quality gates center, integrations southwest, Engineering specialist desks southeast."
      />
      {roster.positioned.map(({ agent, role }) => {
        return (
          <button
            key={agent.agent_id}
            className="canvas-agent"
            style={{
              left: `${(role.x / W) * 100}%`,
              top: `${(Math.min(role.y, 594) / H) * 100}%`,
            }}
            aria-label={`${role.name}: ${activityLabels[agent.activity]}. Inspect agent`}
            aria-pressed={selected === agent.agent_id}
            onClick={() => onSelect(agent.agent_id)}
            title={`${role.name} · ${activityLabels[agent.activity]}`}
          />
        );
      })}
      {(roster.specialists.length > 0 || roster.integrations.length > 0) && (
        <div className="canvas-roster-controls">
          <RosterPager
            label="Integrations"
            count={roster.integrations.length}
            page={roster.integrationPage}
            pages={roster.integrationPages}
            perPage={integrationsPerPage}
            onPage={setIntegrationPage}
          />
          <RosterPager
            label="Engineering specialists"
            count={roster.specialists.length}
            page={roster.specialistPage}
            pages={roster.specialistPages}
            perPage={specialistsPerPage}
            onPage={setSpecialistPage}
          />
        </div>
      )}
    </div>
  );
}
function RosterPager({
  label,
  count,
  page,
  pages,
  perPage,
  onPage,
}: {
  label: string;
  count: number;
  page: number;
  pages: number;
  perPage: number;
  onPage: (page: number) => void;
}) {
  if (!count) return <span />;
  return (
    <div className="canvas-roster-group" aria-label={`${label} desks`}>
      <button
        aria-label={`Previous ${label} page`}
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
      >
        ‹
      </button>
      <span aria-live="polite">
        {label} {page * perPage + 1}–{Math.min(count, (page + 1) * perPage)} of{" "}
        {count}
      </span>
      <button
        aria-label={`Next ${label} page`}
        disabled={page + 1 >= pages}
        onClick={() => onPage(page + 1)}
      >
        ›
      </button>
    </div>
  );
}
