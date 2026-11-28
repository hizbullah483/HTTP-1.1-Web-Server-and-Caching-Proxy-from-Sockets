import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

fig, ax = plt.subplots(figsize=(16, 9.6))
ax.set_xlim(0, 16)
ax.set_ylim(-1.2, 9.4)
ax.axis("off")

def subnet(x0, x1, color, label, lx):
    ax.add_patch(Rectangle((x0, 1.0), x1 - x0, 6.5, facecolor=color, edgecolor="#555", lw=1.2, alpha=0.35))
    ax.text(lx, 7.15, label, ha="center", va="center", fontsize=10, fontweight="bold")

def node(cx, cy, w, h, title, sub, fc):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.03",
                                facecolor=fc, edgecolor="black", lw=1.3, zorder=3))
    ax.text(cx, cy + 0.3, title, ha="center", va="center", fontsize=10, fontweight="bold", zorder=4)
    ax.text(cx, cy - 0.15, sub, ha="center", va="center", fontsize=8, zorder=4)

def link(p, q, l1="", l2=""):
    ax.plot([p[0], q[0]], [p[1], q[1]], color="black", lw=2, zorder=2)
    for t, lab in ((0.14, l1), (0.86, l2)):
        if lab:
            ax.text(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t + 0.2, lab, fontsize=7.5,
                    ha="center", color="#222", zorder=5, bbox=dict(fc="white", ec="none", pad=0.6))

def flow(pts, color, label, lx, ly):
    xs = [p[0] for p in pts[:-1]]
    ys = [p[1] for p in pts[:-1]]
    ax.plot(xs, ys, color=color, lw=2.2, ls="--", zorder=1)
    ax.annotate("", xy=pts[-1], xytext=pts[-2], arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2))
    ax.text(lx, ly, label, ha="center", va="center", fontsize=9, color=color, fontweight="bold")

# Subnets
subnet(0.2, 6.5, "#aed6f1", "10.10.1.0/24 - client LAN (gw 10.10.1.1)", 3.8)
subnet(6.5, 10.5, "#f9e79f", "10.10.2.0/24 - router transit", 8.5)
subnet(10.5, 15.8, "#abebc6", "10.10.3.0/24 - server LAN (gw 10.10.3.1)", 12.9)

# Nodes
node(1.6, 6.0, 2.4, 1.2, "Client", "10.10.1.10", "#fdfefe")
node(1.6, 2.6, 2.4, 1.2, "Caching proxy", "10.10.1.20:8888", "#fdfefe")
node(4.0, 4.3, 1.5, 1.0, "sw (br0)", "Linux bridge", "#d5d8dc")
node(6.5, 4.3, 1.5, 1.5, "R1", "eth1 10.10.1.1\neth2 10.10.2.1", "#f5cba7")
node(10.5, 4.3, 1.5, 1.5, "R2", "eth1 10.10.2.2\neth2 10.10.3.1", "#f5cba7")
node(13.5, 4.3, 1.8, 1.2, "Origin server", "10.10.3.10:8080", "#fdfefe")

# Links with interface names
link((2.8, 5.9), (3.4, 4.7), "eth1", "eth1")
link((2.8, 2.7), (3.4, 3.9), "eth1", "eth2")
link((4.75, 4.3), (5.75, 4.3), "eth3", "eth1")
link((7.25, 4.3), (9.75, 4.3), "eth2", "eth1")
link((11.25, 4.3), (12.6, 4.3), "eth2", "eth1")

# Impairment marker
ax.text(8.5, 5.0, "netem delay (RTT/2 each side)\n+ tbf 10 Mbit/s", ha="center", fontsize=8,
        color="#c0392b", fontweight="bold")

# Flows
flow([(0.9, 6.6), (0.9, 8.0), (15.2, 8.0), (15.2, 4.45), (14.4, 4.45)], "#d35400",
     "Modes A/B: client -> origin direct, HTTP :8080 (A: Connection: close, B: keep-alive)", 8.0, 8.3)
flow([(0.9, 2.0), (0.9, 0.4), (15.2, 0.4), (15.2, 4.15), (14.4, 4.15)], "#1e8449",
     "Mode C: proxy -> origin, HTTP :8080 (persistent upstream, cache validation)", 8.0, 0.1)


flow([(2.0, 5.4), (2.0, 4.6), (3.25, 4.6)], "#2874a6", "", 0, 0)
flow([(3.25, 4.0), (2.0, 4.0), (2.0, 3.2)], "#2874a6", "", 0, 0)
ax.text(0.45, 4.3, "Mode C: client -> proxy\nHTTP :8888\nvia sw", ha="left", va="center", fontsize=7.5, color="#2874a6", fontweight="bold")

# Capture points
cap = dict(fontsize=8, color="#7b241c", ha="center", bbox=dict(fc="#fcf3cf", ec="#7b241c", pad=2))
ax.text(3.9, 2.0, "capture: proxy eth1 (tcp 8888)", **cap)
ax.text(8.0, 3.0, "capture: R1 eth2 (direct A/B, tcp 8080)", **cap)
ax.text(12.4, 3.0, "capture: R2 eth2 (proxy-origin, tcp 8080)", **cap)

ax.text(8, 9.1, "Project 20 - Network architecture, addressing plan and flows", ha="center",
        fontsize=14, fontweight="bold")
ax.text(8, -0.55, "Nodes are Linux network namespaces (containerlab); sw is a Linux bridge. Static routes, IP forwarding on R1 and R2.",
        ha="center", fontsize=8.5)
ax.text(8, -0.95, "Express dashboard (:3000) runs outside the measured path and only reads results/.",
        ha="center", fontsize=8.5)

import os
os.makedirs(os.path.expanduser("~/http20/diagram"), exist_ok=True)
out = os.path.expanduser("~/http20/diagram/architecture.png")
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print("saved", out)
