import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional
import pandas as pd

# --- MODIFICA MANUALE PER OGNI REPOSITORY ---
REPO_PATH = Path(r"/Users/antonellomaddalena/progetto_tamburri/Commons-validator/commons-validator")
EXTRACTION_DIR = Path(r"/Users/antonellomaddalena/progetto_tamburri/Commons-validator/estrazione")
BUILD_OUT_DIR = Path(r"/Users/antonellomaddalena/progetto_tamburri/Commons-validator/build_logs")

# Se vuoto, prova a ricavarlo dal nome della cartella di REPO_PATH
PROJECT_NAME = ""

# Percorsi JAVA_HOME disponibili (aggiorna jdk8 con l'output di: /usr/libexec/java_home -v 1.8)
JDK_CANDIDATES: dict[str, Path] = {
    "jdk8": Path("/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home"),
    "jdk17": Path("/Library/Java/JavaVirtualMachines/jdk-17.jdk/Contents/Home"),
}

# Ordine con cui provare i JDK per ogni release che ha pom.xml
JDK_TRY_ORDER: list[str] = ["jdk8", "jdk17"]

# Comando di build (-e mostra i dettagli dell'errore nei log in caso di fallimento)
BUILD_CMD = ["mvn", "-B", "-e", "test-compile", "-DskipTests"]

# Pulisce modifiche locali e file non tracciati (es. target/) prima di ogni checkout
CLEAN_BEFORE_CHECKOUT = True
# --------------------------------------------


def sanitize_filename_part(value: str) -> str:
    """Rende sicuro un nome (es. un tag Git con '/') per usarlo in un nome file."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def make_env_for_jdk(java_home: Optional[Path]) -> dict[str, str]:
    env = os.environ.copy()
    if java_home is not None:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = f"{java_home / 'bin'}:{env.get('PATH', '')}"
    return env


def run_cmd(
    cmd: list[str],
    cwd: Path,
    log_file: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    append: bool = False,
) -> tuple[int, float]:
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
    )
    elapsed = round(time.perf_counter() - start, 2)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        block = (
            f"CMD: {' '.join(cmd)}\n"
            f"JAVA_HOME: {env.get('JAVA_HOME', '') if env else ''}\n"
            f"RETURN_CODE: {proc.returncode}\n"
            f"ELAPSED_SEC: {elapsed}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n\n--- STDERR ---\n{proc.stderr}\n"
            f"{'=' * 60}\n"
        )
        mode = "a" if append else "w"
        with log_file.open(mode, encoding="utf-8") as f:
            f.write(block)

    return proc.returncode, elapsed


def main() -> None:
    project_name = PROJECT_NAME.strip() or REPO_PATH.name
    releases_csv = EXTRACTION_DIR / f"{project_name}_releases.csv"

    if not releases_csv.exists():
        raise FileNotFoundError(f"File release non trovato: {releases_csv}")

    BUILD_OUT_DIR.mkdir(parents=True, exist_ok=True)
    logs_dir = BUILD_OUT_DIR / f"{project_name}_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    available_jdks: dict[str, Path] = {
        name: path for name, path in JDK_CANDIDATES.items() if path.exists()
    }
    ordered_jdks = [name for name in JDK_TRY_ORDER if name in available_jdks]

    if not ordered_jdks:
        raise RuntimeError(
            "Nessun JDK valido trovato in JDK_CANDIDATES. Controlla i percorsi con '/usr/libexec/java_home -V'."
        )

    base_env = make_env_for_jdk(None)
    releases_df = pd.read_csv(releases_csv).sort_values("ordine")
    results = []

    for _, row in releases_df.iterrows():
        ordine = int(row["ordine"])
        tag = str(row["tag"])
        commit_hash = str(row["commit_hash"])
        safe_tag = sanitize_filename_part(tag)
        log_path = logs_dir / f"{ordine:02d}_{safe_tag}.log"

        if CLEAN_BEFORE_CHECKOUT:
            run_cmd(["git", "reset", "--hard", "HEAD"], cwd=REPO_PATH, env=base_env)
            run_cmd(["git", "clean", "-fd"], cwd=REPO_PATH, env=base_env)

        print(f"[{ordine}/{len(releases_df)}] Checkout {tag} ({commit_hash[:8]})...")
        co_code, _ = run_cmd(["git", "checkout", "--detach", commit_hash], cwd=REPO_PATH, env=base_env)

        if co_code != 0:
            results.append({
                "project": project_name,
                "ordine": ordine,
                "tag": tag,
                "commit_hash": commit_hash,
                "checkout_ok": False,
                "build_ok": False,
                "jdk_used": "",
                "status_reason": "checkout_failed",
                "build_seconds": 0.0,
                "log_file": str(log_path),
            })
            print(f"  -> Errore nel checkout di {tag}")
            continue

        pom_file = REPO_PATH / "pom.xml"
        if not pom_file.exists():
            log_path.write_text(
                f"SKIPPED: pom.xml non presente nella root per il tag {tag} ({commit_hash}).\n",
                encoding="utf-8",
            )
            results.append({
                "project": project_name,
                "ordine": ordine,
                "tag": tag,
                "commit_hash": commit_hash,
                "checkout_ok": True,
                "build_ok": False,
                "jdk_used": "",
                "status_reason": "missing_pom",
                "build_seconds": 0.0,
                "log_file": str(log_path),
            })
            print(f"  -> Saltata: pom.xml assente su {tag} | Log: {log_path.name}")
            continue

        build_ok = False
        jdk_used = ""
        total_elapsed = 0.0

        for idx, jdk_name in enumerate(ordered_jdks):
            jdk_path = available_jdks[jdk_name]
            jdk_env = make_env_for_jdk(jdk_path)
            print(f"  -> Build con {jdk_name}: {' '.join(BUILD_CMD)}")
            build_code, elapsed = run_cmd(
                BUILD_CMD,
                cwd=REPO_PATH,
                log_file=log_path,
                env=jdk_env,
                append=(idx > 0),
            )
            total_elapsed = round(total_elapsed + elapsed, 2)

            if build_code == 0:
                build_ok = True
                jdk_used = jdk_name
                break

        status_reason = "ok" if build_ok else "build_failed"
        results.append({
            "project": project_name,
            "ordine": ordine,
            "tag": tag,
            "commit_hash": commit_hash,
            "checkout_ok": True,
            "build_ok": build_ok,
            "jdk_used": jdk_used,
            "status_reason": status_reason,
            "build_seconds": total_elapsed,
            "log_file": str(log_path),
        })

        if build_ok:
            print(f"  -> Build OK con {jdk_used} ({total_elapsed}s) | Log: {log_path.name}")
        else:
            print(f"  -> Build FALLITA su {ordered_jdks} ({total_elapsed}s) | Log: {log_path.name}")

    status_df = pd.DataFrame(results)
    status_csv = BUILD_OUT_DIR / f"{project_name}_build_status.csv"
    status_df.to_csv(status_csv, index=False, encoding="utf-8")

    print("\n--- Riepilogo build ---")
    print(status_df[["ordine", "tag", "checkout_ok", "build_ok", "jdk_used", "status_reason", "build_seconds"]])
    print(f"\nReport salvato in: {status_csv}")


if __name__ == "__main__":
    main()
