import os
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import requests
import shutil

# --- 1. CONFIGURAZIONE PERCORSI, JDK E SONARQUBE ---
REPO_DIR = Path(r"C:\Users\antoc\Desktop\MAGISTRALE\Evoluzione e qualità del software\progetto\gson")
OUT_DIR = Path(r"C:\Users\antoc\Desktop\MAGISTRALE\Evoluzione e qualità del software\progetto\analisi\output")
INTERVALS_CSV = OUT_DIR / "gson_evolution_intervals.csv"

MVN_BIN = Path(r"C:\tools\apache-maven-3.10.2\bin")

JDK_11 = Path(r"C:\Program Files\Eclipse Adoptium\jdk-11.0.30.7-hotspot")
JDK_17 = Path(r"C:\Program Files\Eclipse Adoptium\jdk-17.0.21.10002-hotspot")
JDK_26 = Path(r"C:\Users\antoc\jdk-26")

SONAR_URL = "http://localhost:9000"
SONAR_PROJECT_KEY = "gson"
SONAR_TOKEN = os.environ.get("SONAR_TOKEN", "sqp_ae35b28d12414bb36118e82e07c3618168ae08ac")

# Tutte le 10 release identificate e relativo JDK per la build
RELEASES = [
    ("gson-parent-2.4", "JDK 11"),
    ("gson-parent-2.6", "JDK 11"),
    ("gson-parent-2.7", "JDK 11"),
    ("gson-parent-2.8.0", "JDK 11"),
    ("gson-parent-2.8.9", "JDK 11"),
    ("gson-parent-2.9.1", "JDK 17"),
    ("gson-parent-2.10.1", "JDK 17"),
    ("gson-parent-2.12.0", "JDK 17"),
    ("gson-parent-2.13.2", "JDK 17"),
    ("gson-parent-2.15.0", "JDK 17"),
]

# Metriche richieste all'API di SonarQube
METRIC_KEYS = [
    "ncloc",
    "complexity",
    "cognitive_complexity",
    "duplicated_lines_density",
    "duplicated_lines",
    "sqale_index",
    "code_smells",
    "bugs",
    "vulnerabilities",
    "security_hotspots",
    "violations",
]


def build_env_with_jdk(jdk_path: Path) -> dict:
    env = os.environ.copy()
    env["JAVA_HOME"] = str(jdk_path)
    clean_parts = [
        p for p in env.get("Path", "").split(";")
        if p and not any(k in p.lower() for k in ["jdk-11", "jdk-17", "jdk-21", "jdk-26", "java\\jdk"])
    ]
    env["Path"] = f"{jdk_path}\\bin;" + ";".join(clean_parts)
    return env


def run_cmd(cmd: list[str], cwd: Path, env: dict) -> None:
    resolved_cmd = cmd.copy()

    if resolved_cmd[0] == "mvn":
        mvn_candidates = []
        if MVN_BIN is not None:
            mvn_candidates.append(Path(MVN_BIN) / "mvn.cmd")
            mvn_candidates.append(Path(MVN_BIN) / "mvn.bat")
        found_in_path = shutil.which("mvn.cmd", path=env.get("Path")) or shutil.which("mvn", path=env.get("Path"))
        if found_in_path:
            mvn_candidates.append(Path(found_in_path))

        chosen_mvn = next((p for p in mvn_candidates if p.exists()), None)
        if chosen_mvn is None:
            raise FileNotFoundError(f"Impossibile trovare mvn.cmd in MVN_BIN={MVN_BIN} o nel PATH.")
        resolved_cmd[0] = str(chosen_mvn)
    else:
        exe = shutil.which(resolved_cmd[0], path=env.get("Path"))
        if exe:
            resolved_cmd[0] = exe

    print("  ->", " ".join(resolved_cmd))
    res = subprocess.run(resolved_cmd, cwd=str(cwd), env=env, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Comando fallito ({res.returncode}): {' '.join(resolved_cmd)}")

def adapt_gson_2_4_target(repo_dir: Path) -> None:
    """Adattamento temporaneo del target 1.5 -> 1.6 per gson-parent-2.4."""
    for pom in repo_dir.rglob("pom.xml"):
        txt = pom.read_text(encoding="utf-8", errors="replace")
        new_txt = re.sub(r"<maven\.compiler\.target>\s*1\.5\s*</maven\.compiler\.target>", "<maven.compiler.target>1.6</maven.compiler.target>", txt)
        new_txt = re.sub(r"<target>\s*1\.5\s*</target>", "<target>1.6</target>", new_txt)
        new_txt = re.sub(r"<source>\s*1\.5\s*</source>", "<source>1.6</source>", new_txt)
        if new_txt != txt:
            pom.write_text(new_txt, encoding="utf-8")


def fetch_sonar_measures(sonar_url: str, project_key: str, token: str, metrics: list[str]) -> dict:
    url = f"{sonar_url}/api/measures/component"
    params = {
        "component": project_key,
        "metricKeys": ",".join(metrics),
    }
    resp = requests.get(url, params=params, auth=(token, ""), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    extracted = {}
    for m in data.get("component", {}).get("measures", []):
        key = m.get("metric")
        val = m.get("value")
        extracted[key] = val
    return extracted


def generate_charts(df: pd.DataFrame, out_dir: Path) -> Path:
    labels = [r.replace("gson-parent-", "") for r in df["release"]]

    def to_num(col):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series([None] * len(df))

    ncloc = to_num("ncloc")
    debt = to_num("sqale_index")
    dup = to_num("duplicated_lines_density")
    smells = to_num("code_smells")
    violations = to_num("violations")

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    # 1. Dimensione codice (NCLOC)
    axes[0].plot(labels, ncloc, marker="o", linewidth=2, color="#2b5c8f")
    axes[0].set_ylabel("NCLOC")
    axes[0].set_title("Evoluzione delle metriche SonarQube sulle 10 release di Gson")
    axes[0].grid(True, linestyle="--", alpha=0.4)

    # 2. Remediation Effort / Technical Debt (minuti)
    debt_series = debt if debt.notna().any() else smells
    debt_label = "Technical Debt (min)" if debt.notna().any() else "Code Smells / Issues"
    axes[1].plot(labels, debt_series, marker="s", linewidth=2, color="#c85a32")
    axes[1].set_ylabel(debt_label)
    axes[1].grid(True, linestyle="--", alpha=0.4)

    # 3. Duplicated Lines Density (%) o Violations
    third_series = dup if dup.notna().any() else violations
    third_label = "Duplicated Lines (%)" if dup.notna().any() else "Violations"
    axes[2].plot(labels, third_series, marker="^", linewidth=2, color="#2e7d5b")
    axes[2].set_ylabel(third_label)
    axes[2].set_xlabel("Release Gson")
    axes[2].grid(True, linestyle="--", alpha=0.4)

    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    chart_path = out_dir / "gson_sonar_trends.png"
    plt.savefig(chart_path, dpi=150)
    plt.close(fig)
    return chart_path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SONAR_TOKEN:
        raise ValueError("Imposta SONAR_TOKEN prima di eseguire lo script.")

    env_jdk11 = build_env_with_jdk(JDK_11)
    env_jdk17 = build_env_with_jdk(JDK_17)

    rows = []
    for idx, (tag, jdk_label) in enumerate(RELEASES, start=1):
        print(f"\n=== [{idx}/{len(RELEASES)}] Elaborazione {tag} ({jdk_label}) ===")
        run_cmd(["git", "checkout", "--force", "."], REPO_DIR, env_jdk17)
        run_cmd(["git", "clean", "-fd"], REPO_DIR, env_jdk17)
        run_cmd(["git", "checkout", tag], REPO_DIR, env_jdk17)

        if tag == "gson-parent-2.4":
            adapt_gson_2_4_target(REPO_DIR)

        build_env = env_jdk11 if jdk_label == "JDK 11" else env_jdk17
        run_cmd(["mvn", "clean", "compile", "-DskipTests"], REPO_DIR, build_env)

        # Scansione SonarQube eseguita con JDK 17
        run_cmd(
            [
                "mvn",
                "org.sonarsource.scanner.maven:sonar-maven-plugin:sonar",
                "-DskipTests",
                f"-Dsonar.projectKey={SONAR_PROJECT_KEY}",
                f"-Dsonar.host.url={SONAR_URL}",
                f"-Dsonar.token={SONAR_TOKEN}",
            ],
            REPO_DIR,
            env_jdk17,
        )

        # Ripristina eventuali modifiche locali (es. target 1.6 su 2.4)
        run_cmd(["git", "checkout", "--force", "."], REPO_DIR, env_jdk17)

        measures = fetch_sonar_measures(SONAR_URL, SONAR_PROJECT_KEY, SONAR_TOKEN, METRIC_KEYS)
        row = {"order": idx, "release": tag, "build_jdk": jdk_label}
        for k in METRIC_KEYS:
            row[k] = measures.get(k)
        rows.append(row)

    df_sonar = pd.DataFrame(rows)
    sonar_csv = OUT_DIR / "gson_sonar_metrics.csv"
    df_sonar.to_csv(sonar_csv, index=False)
    print(f"\nCSV metriche SonarQube salvato in: {sonar_csv}")

    # Integrazione opzionale con gson_evolution_intervals.csv
    if INTERVALS_CSV.exists():
        df_int = pd.read_csv(INTERVALS_CSV)
        df_merged = pd.merge(
            df_sonar,
            df_int,
            left_on="release",
            right_on="to_tag",
            how="left",
        )
        merged_csv = OUT_DIR / "gson_combined_evolution_sonar.csv"
        df_merged.to_csv(merged_csv, index=False)
        print(f"CSV combinato (Sonar + Evoluzione) salvato in: {merged_csv}")

    chart_path = generate_charts(df_sonar, OUT_DIR)
    print(f"Grafico salvato in: {chart_path}")


if __name__ == "__main__":
    main()