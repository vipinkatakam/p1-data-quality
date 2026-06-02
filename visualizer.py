import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

OUTPUT_FOLDER = "output"

def load_report(filename):
    path = os.path.join(OUTPUT_FOLDER, filename)
    with open(path, 'r') as f:
        return json.load(f)

def plot_validation_summary(validation_data):
    """Bar chart of violations by rule"""
    violations = validation_data.get("violations_by_rule", {})

    if not violations:
        print("No violations to chart — using simulated data for demo")
        violations = {
            "actor.login:not_null":    30,
            "type:value_in_set":       30,
            "repo.name:not_null":      20,
            "created_at:regex_match":  20
        }

    labels  = [k.split(":")[0] + "\n(" + k.split(":")[1] + ")"
               for k in violations.keys()]
    values  = list(violations.values())
    colors  = ["#ef4444", "#f97316", "#eab308", "#a78bfa"][:len(values)]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values, color=colors, width=0.5,
                  edgecolor="white", linewidth=1.5)

    # value labels on top of bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + 0.5,
                f"{val:,}", ha="center", va="bottom",
                fontsize=11, fontweight="600", color="#111")

    ax.set_title("Validation Violations by Rule",
                 fontsize=14, fontweight="700", pad=16)
    ax.set_ylabel("Violation Count", fontsize=11)
    ax.set_ylim(0, max(values) * 1.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_facecolor("#fafafa")
    fig.patch.set_facecolor("#ffffff")
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    path = os.path.join(OUTPUT_FOLDER, "chart_violations.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved → {path}")

def plot_reconciliation_summary(recon_data):
    """Stacked bar showing source vs processed vs lost per test"""

    tests  = recon_data.get("tests", [])
    labels = ["Normal Run", "5% Loss Simulated", "Duplicates Injected"]

    relevant   = [t["counts"]["relevant"]   for t in tests]
    processed  = [t["counts"]["processed"]  for t in tests]
    dropped    = [t["counts"]["dropped"]    for t in tests]
    lost       = [abs(t["counts"]["lost"])  for t in tests]
    dupes      = [t["counts"]["duplicates"] for t in tests]

    x     = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(11, 6))

    bars1 = ax.bar(x - width/2, relevant,  width,
                   label="Expected (relevant source records)",
                   color="#3b82f6", alpha=0.85)
    bars2 = ax.bar(x + width/2, processed, width,
                   label="Processed (landed in DB)",
                   color="#22c55e", alpha=0.85)

    # mark lost records in red on top of processed bar
    for i, (proc, ls, dp) in enumerate(zip(processed, lost, dupes)):
        if ls > 0:
            ax.bar(x[i] + width/2, ls, width,
                   bottom=proc, color="#ef4444",
                   alpha=0.9, label="Lost" if i == 1 else "")
            ax.text(x[i] + width/2, proc + ls + 1000,
                    f"-{ls:,}", ha="center", color="#ef4444",
                    fontsize=10, fontweight="700")
        if dp > 0:
            ax.bar(x[i] + width/2, dp, width,
                   bottom=proc, color="#f97316",
                   alpha=0.9, label="Duplicates" if i == 2 else "")
            ax.text(x[i] + width/2, proc + dp + 1000,
                    f"+{dp}", ha="center", color="#f97316",
                    fontsize=10, fontweight="700")

    # status badges
    statuses = [t["status"] for t in tests]
    for i, status in enumerate(statuses):
        color = "#16a34a" if status == "PASSED" else "#dc2626"
        ax.text(x[i], max(relevant) * 1.08,
                f"{'✓' if status == 'PASSED' else '✗'} {status}",
                ha="center", fontsize=11, fontweight="700", color=color)

    ax.set_title("Reconciliation — Source vs Processed Records",
                 fontsize=14, fontweight="700", pad=20)
    ax.set_ylabel("Record Count", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylim(0, max(relevant) * 1.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_facecolor("#fafafa")
    fig.patch.set_facecolor("#ffffff")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(loc="upper right", fontsize=10)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda val, _: f"{int(val):,}"))

    plt.tight_layout()
    path = os.path.join(OUTPUT_FOLDER, "chart_reconciliation.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved → {path}")

def plot_pipeline_health(validation_data, recon_data):
    """Single dashboard — 4 key metrics as big numbers"""

    total_events = validation_data.get("total_events", 741104)
    violations   = validation_data.get("total_violations", 100)
    clean_rate   = round((total_events - violations) / total_events * 100, 1)

    recon_test1  = recon_data["tests"][0]
    processed    = recon_test1["counts"]["processed"]
    relevant     = recon_test1["counts"]["relevant"]
    integrity    = round(processed / relevant * 100, 2)

    fig, axes = plt.subplots(1, 4, figsize=(14, 4))
    fig.patch.set_facecolor("#ffffff")

    metrics = [
        ("Total Events\nValidated",  f"{total_events:,}",  "#3b82f6"),
        ("Violations\nDetected",     f"{violations:,}",    "#ef4444"),
        ("Data Clean\nRate",         f"{clean_rate}%",     "#22c55e"),
        ("Record\nIntegrity",        f"{integrity}%",      "#a78bfa"),
    ]

    for ax, (label, value, color) in zip(axes, metrics):
        ax.set_facecolor("#f8fafc")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # colored top border
        ax.axhline(y=0.97, xmin=0.05, xmax=0.95,
                   color=color, linewidth=4, solid_capstyle="round")

        ax.text(0.5, 0.58, value, ha="center", va="center",
                fontsize=26, fontweight="800", color=color,
                transform=ax.transAxes)
        ax.text(0.5, 0.25, label, ha="center", va="center",
                fontsize=11, color="#6b7280",
                transform=ax.transAxes)

        for spine in ax.spines.values():
            spine.set_edgecolor("#e5e7eb")
            spine.set_linewidth(1)
        ax.set_axis_on()

    fig.suptitle("Pipeline Health Dashboard",
                 fontsize=15, fontweight="700", y=1.02)
    plt.tight_layout(pad=1.5)
    path = os.path.join(OUTPUT_FOLDER, "chart_dashboard.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved → {path}")

if __name__ == "__main__":
    print("Generating charts...\n")

    # load reports generated by previous scripts
    validation_data = load_report("validation_report.json")
    recon_data      = load_report("reconciliation_report.json")

    print("1. Violations by rule chart")
    plot_validation_summary(validation_data)

    print("2. Reconciliation comparison chart")
    plot_reconciliation_summary(recon_data)

    print("3. Pipeline health dashboard")
    plot_pipeline_health(validation_data, recon_data)

    print("\nAll charts saved to output/ folder.")
    print("Open them in File Explorer to see your visuals.")