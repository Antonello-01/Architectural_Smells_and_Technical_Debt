import re
from pathlib import Path
import pandas as pd
from pydriller import Git, Repository

# --- MODIFICA MANUALE PER OGNI REPOSITORY ---
REPO_PATH = r"/Users/antonellomaddalena/progetto_tamburri/JUnit4/junit4"
OUT_DIR = Path(r"/Users/antonellomaddalena/progetto_tamburri/JUnit4/estrazione")

# Se vuoto, usa automaticamente il nome della cartella in REPO_PATH (es. "junit4")
PROJECT_NAME = ""

# Numero massimo di ultime release da estrarre automaticamente (es. 10)
NUM_RELEASES = 10

# Valore predefinito per jdk sulle release rilevate automaticamente
DEFAULT_JDK = ""

# Lascia [] per estrarre sempre le ultime NUM_RELEASES release dal repository Git.
# Se in un caso particolare vuoi forzare una lista specifica, inseriscila qui:
# [{"tag": "r4.13.2", "jdk": "JDK 8", "note": ""}]
MANUAL_RELEASES: list[dict] = []
# --------------------------------------------


def get_last_release_tags(git_repo: Git, limit: int = 10, default_jdk: str = "") -> list[dict]:
    """Estrae le ultime `limit` release dal repository Git in base alla data del commit."""
    repo = git_repo.repo
    candidates = []

    for tag_ref in repo.tags:
        tag_name = tag_ref.name

        # Esclude tag tipici di pre-release, beta, release candidate o snapshot
        if re.search(r"(alpha|beta|rc|snapshot|m\d+|b\d+)", tag_name, re.IGNORECASE):
            continue

        commit = git_repo.get_commit_from_tag(tag_name)
        if commit is None:
            # Fallback diretto sul commit del tag se get_commit_from_tag non lo risolve
            commit_hash = tag_ref.commit.hexsha
            commit = git_repo.get_commit(commit_hash)

        if commit is not None:
            candidates.append({
                "tag": tag_name,
                "jdk": default_jdk,
                "note": "auto-selected (last releases)",
                "_date": commit.committer_date,
            })

    # Ordina dal commit più vecchio al più recente e prende le ultime `limit` release
    candidates.sort(key=lambda item: item["_date"])
    selected = candidates[-limit:] if limit > 0 else candidates

    return [
        {"tag": item["tag"], "jdk": item["jdk"], "note": item["note"]}
        for item in selected
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    project_name = PROJECT_NAME.strip() or Path(REPO_PATH).name

    git_repo = Git(REPO_PATH)

    if MANUAL_RELEASES:
        releases_to_use = MANUAL_RELEASES
    else:
        releases_to_use = get_last_release_tags(
            git_repo=git_repo,
            limit=NUM_RELEASES,
            default_jdk=DEFAULT_JDK,
        )

    if len(releases_to_use) < 2:
        raise ValueError(
            f"Trovate solo {len(releases_to_use)} release valide in '{project_name}': "
            "ne servono almeno 2 per calcolare gli intervalli evolutivi."
        )

    release_rows = []
    for rel in releases_to_use:
        tag = rel["tag"]
        commit = git_repo.get_commit_from_tag(tag)
        if commit is None:
            raise ValueError(f"Tag '{tag}' non trovato nel repository '{REPO_PATH}'.")

        release_rows.append({
            "project": project_name,
            "tag": tag,
            "commit_hash": commit.hash,
            "commit_date": commit.committer_date.isoformat(),
            "_dt": commit.committer_date,
            "jdk": rel.get("jdk", DEFAULT_JDK),
            "note": rel.get("note", ""),
        })

    # Ordina sempre cronologicamente in base alla data del commit
    release_rows.sort(key=lambda r: r["_dt"])
    for idx, row in enumerate(release_rows, start=1):
        row["ordine"] = idx

    releases_df = pd.DataFrame([
        {k: v for k, v in row.items() if k != "_dt"}
        for row in release_rows
    ])
    releases_csv = OUT_DIR / f"{project_name}_releases.csv"
    releases_df.to_csv(releases_csv, index=False, encoding="utf-8")

    interval_rows = []
    for i in range(len(release_rows) - 1):
        start_rel = release_rows[i]
        end_rel = release_rows[i + 1]

        commit_count = 0
        authors = set()
        total_files_touched = 0
        java_files_touched = 0
        lines_added = 0
        lines_deleted = 0

        # PyDriller: from_commit è esclusivo, to_commit è inclusivo
        repo_miner = Repository(
            path_to_repo=REPO_PATH,
            from_commit=start_rel["commit_hash"],
            to_commit=end_rel["commit_hash"],
        )

        for commit in repo_miner.traverse_commits():
            commit_count += 1
            if commit.author and commit.author.email:
                authors.add(commit.author.email.lower())

            for mod in commit.modified_files:
                total_files_touched += 1
                filename = mod.new_path or mod.old_path or ""
                if filename.endswith(".java"):
                    java_files_touched += 1
                lines_added += mod.added_lines or 0
                lines_deleted += mod.deleted_lines or 0

        interval_rows.append({
            "project": project_name,
            "from_tag": start_rel["tag"],
            "to_tag": end_rel["tag"],
            "from_date": start_rel["commit_date"],
            "to_date": end_rel["commit_date"],
            "jdk_to_tag": end_rel["jdk"],
            "commits": commit_count,
            "distinct_authors": len(authors),
            "files_touched": total_files_touched,
            "java_files_touched": java_files_touched,
            "lines_added": lines_added,
            "lines_deleted": lines_deleted,
            "code_churn": lines_added + lines_deleted,
        })

    intervals_df = pd.DataFrame(interval_rows)
    intervals_csv = OUT_DIR / f"{project_name}_evolution_intervals.csv"
    intervals_df.to_csv(intervals_csv, index=False, encoding="utf-8")

    print(f"Completato per '{project_name}' ({len(release_rows)} release). File salvati in: {OUT_DIR}")
    print("\n--- Ultime release selezionate ---")
    print(releases_df[["ordine", "tag", "commit_date", "jdk"]])
    print("\n--- Intervalli estratti ---")
    print(intervals_df[["from_tag", "to_tag", "commits", "java_files_touched", "code_churn"]])


if __name__ == "__main__":
    main()