from pathlib import Path
import pandas as pd
from pydriller import Git, Repository

REPO_PATH = r"C:\Users\antoc\Desktop\MAGISTRALE\Evoluzione e qualità del software\progetto\repos\thumbnailator"
OUT_DIR = Path(r"C:\Users\antoc\Desktop\MAGISTRALE\Evoluzione e qualità del software\progetto\analisi_thumbnailator\output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

RELEASES = [
    {"tag": "0.4.1",  "jdk": "JDK 11", "note": "Target 1.5 adattato temporaneamente a 1.7 in build"},
    {"tag": "0.4.3",  "jdk": "JDK 11", "note": "Target 1.5 adattato temporaneamente a 1.7 in build"},
    {"tag": "0.4.5",  "jdk": "JDK 11", "note": ""},
    {"tag": "0.4.7",  "jdk": "JDK 11", "note": ""},
    {"tag": "0.4.8",  "jdk": "JDK 11", "note": "Target 1.5 adattato temporaneamente a 1.7 in build"},
    {"tag": "0.4.10", "jdk": "JDK 11", "note": "Target 1.5 adattato temporaneamente a 1.7 in build"},
    {"tag": "0.4.12", "jdk": "JDK 11", "note": "Target 1.5 adattato temporaneamente a 1.7 in build"},
    {"tag": "0.4.16", "jdk": "JDK 17", "note": ""},
    {"tag": "0.4.18", "jdk": "JDK 17", "note": ""},
    {"tag": "0.4.21", "jdk": "JDK 17", "note": ""},
]


def main():
    git_repo = Git(REPO_PATH)
    release_rows = []

    for idx, rel in enumerate(RELEASES, start=1):
        commit = git_repo.get_commit_from_tag(rel["tag"])
        release_rows.append({
            "ordine": idx,
            "tag": rel["tag"],
            "commit_hash": commit.hash,
            "commit_date": commit.committer_date.isoformat(),
            "jdk": rel["jdk"],
            "note": rel["note"],
        })

    releases_df = pd.DataFrame(release_rows)
    releases_df.to_csv(OUT_DIR / "thumbnailator_releases.csv", index=False, encoding="utf-8")

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
    intervals_df.to_csv(OUT_DIR / "thumbnailator_evolution_intervals.csv", index=False, encoding="utf-8")

    print("Fatto! File salvati in:", OUT_DIR)
    print("\n--- Riepilogo release ---")
    print(releases_df[["ordine", "tag", "commit_date", "jdk"]])
    print("\n--- Riepilogo intervalli ---")
    print(intervals_df[["from_tag", "to_tag", "commits", "java_files_touched", "code_churn"]])


if __name__ == "__main__":
    main()