#!/usr/bin/env python3
"""Generate ai_agents_kvcache.excalidraw.

The diagram shows many AI agents. The agents read data from a database and
write data to it. The agents send prompts to an LLM and receive responses.
The LLM uses a KV cache. Each color shows the KV cache entries of one agent.
"""
import json
import math
import random
from pathlib import Path

random.seed(7)
OUT = Path(__file__).with_name("ai_agents_kvcache.excalidraw")

CLAUDE_ORANGE = "#d97757"
INK = "#1e1e1e"
AGENTS = [
    # name, task, stroke, fill, kv blocks
    ("Agent 1", "Task: research", "#1971c2", "#a5d8ff", "blk 8-15, 24-27"),
    ("Agent 2", "Task: write code", "#2f9e44", "#b2f2bb", "blk 16-19"),
    ("Agent 3", "Task: test code", "#9c36b5", "#eebefa", "blk 20-23, 28"),
    ("Agent 4", "Task: summarize", "#0c8599", "#99e9f2", "blk 29-31"),
]

elements = []
_id = 0


def nid(prefix):
    global _id
    _id += 1
    return f"{prefix}{_id}"


def base(kind, x, y, w, h, **kw):
    el = {
        "id": nid(kind[:3]),
        "type": kind,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": kw.pop("stroke", INK),
        "backgroundColor": kw.pop("bg", "transparent"),
        "fillStyle": kw.pop("fill", "solid"),
        "strokeWidth": kw.pop("sw", 2),
        "strokeStyle": kw.pop("style", "solid"),
        "roughness": kw.pop("rough", 1),
        "opacity": 100,
        "groupIds": kw.pop("groups", []),
        "frameId": None,
        "roundness": kw.pop("roundness", None),
        "seed": random.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": random.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }
    el.update(kw)
    elements.append(el)
    return el


def rect(x, y, w, h, **kw):
    kw.setdefault("roundness", {"type": 3})
    return base("rectangle", x, y, w, h, **kw)


def ellipse(x, y, w, h, **kw):
    kw.setdefault("roundness", {"type": 2})
    return base("ellipse", x, y, w, h, **kw)


def text(x, y, s, size=20, color=INK, align="left", container=None, groups=None, family=1):
    lines = s.split("\n")
    w = max(len(l) for l in lines) * size * 0.55
    h = len(lines) * size * 1.25
    if align == "center" and container is None:
        x -= w / 2
    el = base(
        "text", x, y, w, h, stroke=color, groups=groups or [], rough=1,
        text=s, originalText=s, fontSize=size, fontFamily=family,
        textAlign=align, verticalAlign="middle" if container else "top",
        baseline=round(size * 0.9), containerId=container["id"] if container else None,
        lineHeight=1.25, autoResize=True,
    )
    if container:
        container["boundElements"].append({"id": el["id"], "type": "text"})
        el["x"] = container["x"] + (container["width"] - w) / 2
        el["y"] = container["y"] + (container["height"] - h) / 2
    return el


def line(points, **kw):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = points[0]
    rel = [[px - x0, py - y0] for px, py in points]
    return base(
        "line", x0, y0, max(xs) - min(xs), max(ys) - min(ys),
        points=rel, lastCommittedPoint=None, startBinding=None, endBinding=None,
        startArrowhead=None, endArrowhead=None, **kw,
    )


def arrow(p0, p1, start=None, end=None, label=None, color=INK, style="solid", label_size=16,
          below=False):
    (x0, y0), (x1, y1) = p0, p1
    a = base(
        "arrow", x0, y0, abs(x1 - x0), abs(y1 - y0), stroke=color, style=style,
        roundness={"type": 2}, points=[[0, 0], [x1 - x0, y1 - y0]],
        lastCommittedPoint=None, startArrowhead=None, endArrowhead="arrow",
        startBinding=None, endBinding=None, elbowed=False,
    )
    for key, shape in (("startBinding", start), ("endBinding", end)):
        if shape is not None:
            a[key] = {"elementId": shape["id"], "focus": 0, "gap": 6}
            shape["boundElements"].append({"id": a["id"], "type": "arrow"})
    if label:
        # The label sits above the arrow midpoint (or below it).
        ty = (y0 + y1) / 2 + (6 if below else -label_size * 1.25 - 6)
        text((x0 + x1) / 2, ty, label, size=label_size, color=color, align="center")
    return a


def claude_logo(cx, cy, r, groups):
    """A Claude-style starburst: orange rays out from one center point."""
    n = 11
    for i in range(n):
        ang = 2 * math.pi * i / n + 0.15
        length = r * (0.75 + 0.25 * ((i * 7) % 3) / 2)
        inner = r * 0.12
        line(
            [
                [cx + inner * math.cos(ang), cy + inner * math.sin(ang)],
                [cx + length * math.cos(ang), cy + length * math.sin(ang)],
            ],
            stroke=CLAUDE_ORANGE, sw=4, rough=0, roundness={"type": 2}, groups=groups,
        )


# ---------------------------------------------------------------- title
text(870, 20, "AI agents use a database and an LLM with a KV cache", size=36, align="center")
text(
    870, 72,
    "Each agent reads and writes data. Each agent sends prompts to the LLM. "
    "The KV cache keeps the entries of each agent.",
    size=18, color="#495057", align="center",
)

# ---------------------------------------------------------------- database
DBX, DBY, DBW, DBH = 60, 140, 260, 680
db_g = ["g-db"]
ellipse(DBX, DBY + DBH - 60, DBW, 60, bg="#e9ecef", groups=db_g)
rect(DBX, DBY + 30, DBW, DBH - 60, bg="#e9ecef", stroke="#e9ecef", roundness=None,
     groups=db_g, rough=0, sw=1)
line([[DBX, DBY + 30], [DBX, DBY + DBH - 30]], groups=db_g)
line([[DBX + DBW, DBY + 30], [DBX + DBW, DBY + DBH - 30]], groups=db_g)
for k in (1, 2, 3, 4, 5):
    yy = DBY + 30 + k * 105
    line([[DBX, yy], [DBX + DBW * 0.5, yy + 26], [DBX + DBW, yy]],
         roundness={"type": 2}, stroke="#868e96", sw=1, groups=db_g)
ellipse(DBX, DBY, DBW, 60, bg="#dee2e6", groups=db_g)
# A transparent hit box for the arrow bindings.
db_hit = rect(DBX, DBY, DBW, DBH, bg="transparent", stroke="transparent", roundness=None,
              groups=db_g, rough=0)
text(DBX + DBW / 2, DBY + 278, "Database", size=32, align="center", groups=db_g)
text(DBX + DBW / 2, DBY + 388, "tables: tasks,\nnotes, results", size=18, color="#495057",
     align="center", groups=db_g)

# ---------------------------------------------------------------- agents
AX, AW, AH = 560, 270, 130
agent_boxes = []
for i, (name, task, stroke, fill, blocks) in enumerate(AGENTS):
    ay = 150 + i * 190
    g = [f"g-agent{i}"]
    box = rect(AX, ay, AW, AH, stroke=stroke, bg=fill, groups=g, sw=3)
    agent_boxes.append(box)
    ellipse(AX + 18, ay + 25, 80, 80, bg="#faf9f5", stroke=stroke, groups=g, sw=1)
    claude_logo(AX + 58, ay + 65, 34, g)
    text(AX + 115, ay + 18, name, size=26, color=stroke, groups=g)
    text(AX + 115, ay + 56, task, size=16, groups=g)
    text(AX + 115, ay + 86, "KV: " + blocks, size=16, color=stroke, groups=g)

# ---------------------------------------------------------------- LLM
LX, LY, LW, LH = 1060, 140, 280, 680
llm = rect(LX, LY, LW, LH, stroke=INK, bg="#fff3bf", sw=3)
text(LX + LW / 2, LY + 170, "LLM", size=40, align="center")
text(LX + LW / 2, LY + 230, "inference server", size=20, color="#495057", align="center")
# A small GPU chip drawing.
rect(LX + 85, LY + 300, 110, 110, bg="#ffffff", stroke=INK, sw=2)
text(LX + LW / 2, LY + 340, "GPU", size=24, align="center")
for k in range(4):
    off = 18 + k * 25
    line([[LX + 85 + off, LY + 300], [LX + 85 + off, LY + 285]], sw=2)
    line([[LX + 85 + off, LY + 410], [LX + 85 + off, LY + 425]], sw=2)
    line([[LX + 85, LY + 300 + off], [LX + 70, LY + 300 + off]], sw=2)
    line([[LX + 195, LY + 300 + off], [LX + 210, LY + 300 + off]], sw=2)

# ---------------------------------------------------------------- KV cache
KX, KY, KW = 1580, 205, 400
ROW = 46
rows = [
    ("Shared: system prompt", "blk 0-7", CLAUDE_ORANGE, "#ffe8cc"),
    ("Agent 1", "blk 8-15", *AGENTS[0][2:4]),
    ("Agent 2", "blk 16-19", *AGENTS[1][2:4]),
    ("Agent 3", "blk 20-23", *AGENTS[2][2:4]),
    ("Agent 1", "blk 24-27", *AGENTS[0][2:4]),
    ("Agent 3", "blk 28", *AGENTS[2][2:4]),
    ("Agent 4", "blk 29-31", *AGENTS[3][2:4]),
    ("Empty", "blk 32-39", "#adb5bd", "#f8f9fa"),
]
kv_h = 60 + ROW * len(rows) + 20
kv = rect(KX, KY, KW, kv_h, stroke=INK, bg="#f8f9fa", sw=3)
text(KX + KW / 2, KY + 14, "KV cache (GPU memory)", size=24, align="center")
for r, (owner, blk, stroke, fill) in enumerate(rows):
    ry = KY + 60 + r * ROW
    g = [f"g-kv{r}"]
    cell = rect(KX + 20, ry, KW - 40, ROW - 8, stroke=stroke, bg=fill, groups=g,
                style="dashed" if owner == "Empty" else "solid")
    ellipse(KX + 32, ry + 11, 16, 16, stroke=stroke, bg=stroke, groups=g)
    text(KX + 58, ry + 8, owner, size=18, color=stroke if owner != "Empty" else "#868e96",
         groups=g)
    text(KX + KW - 115, ry + 8, blk, size=18, color="#495057", groups=g)

# ---------------------------------------------------------------- arrows
for i, box in enumerate(agent_boxes):
    stroke = AGENTS[i][2]
    ay = box["y"]
    first = i == 0
    # Agent <-> database
    arrow((AX - 8, ay + 45), (DBX + DBW + 8, ay + 45), start=box, end=db_hit,
          color=stroke, label="Write data" if first else None)
    arrow((DBX + DBW + 8, ay + 90), (AX - 8, ay + 90), start=db_hit, end=box,
          color=stroke, style="dashed", label="Read data" if first else None, below=True)
    # Agent <-> LLM
    arrow((AX + AW + 8, ay + 45), (LX - 8, ay + 45), start=box, end=llm,
          color=stroke, label="Send prompt" if first else None)
    arrow((LX - 8, ay + 90), (AX + AW + 8, ay + 90), start=llm, end=box,
          color=stroke, style="dashed", label="Receive response" if first else None,
          below=True)

# LLM <-> KV cache
for k, (lbl, dashed) in enumerate([("Find KV entries", False), ("Use KV entries", True),
                                    ("Write new entries", False)]):
    yy = KY + 120 + k * 120
    p0, p1 = (LX + LW + 8, yy), (KX - 8, yy)
    arrow(p1 if dashed else p0, p0 if dashed else p1, start=kv if dashed else llm,
          end=llm if dashed else kv, style="dashed" if dashed else "solid",
          label=lbl, label_size=18)

# ---------------------------------------------------------------- legend
LGX, LGY = 1080, 870
rect(LGX - 20, LGY - 20, 920, 215, stroke="#adb5bd", bg="transparent", style="dashed")
text(LGX, LGY, "Legend", size=22)
arrow((LGX, LGY + 50), (LGX + 70, LGY + 50))
text(LGX + 90, LGY + 38, "Solid arrow: the sender pushes data or a request.", size=18)
arrow((LGX, LGY + 90), (LGX + 70, LGY + 90), style="dashed")
text(LGX + 90, LGY + 78, "Dashed arrow: the receiver gets data or a response.", size=18)
text(LGX, LGY + 128,
     "Color: each color shows one agent. The KV cache rows with that color\n"
     "are the entries of that agent. All agents share the orange rows.", size=18)

doc = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": elements,
    "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
    "files": {},
}
OUT.write_text(json.dumps(doc, indent=1))
print(f"wrote {OUT} ({len(elements)} elements)")
