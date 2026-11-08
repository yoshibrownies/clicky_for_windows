from clicky.version import read_build_info

COMMIT = "b9602de1234567890abcdef1234567890abcdef0"


def make_repo(root, head="ref: refs/heads/feat/initial-app\n"):
    git_dir = root / ".git"
    (git_dir / "refs" / "heads" / "feat").mkdir(parents=True)
    (git_dir / "HEAD").write_text(head)
    return git_dir


def test_reads_branch_and_short_commit_from_a_normal_checkout(tmp_path):
    git_dir = make_repo(tmp_path)
    (git_dir / "refs" / "heads" / "feat" / "initial-app").write_text(COMMIT + "\n")
    info = read_build_info(tmp_path)
    assert (info.branch, info.commit) == ("feat/initial-app", "b9602de")
    assert info.describe() == "b9602de (feat/initial-app)"


def test_reads_packed_refs(tmp_path):
    git_dir = make_repo(tmp_path)
    (git_dir / "packed-refs").write_text(f"# pack-refs with: peeled\n{COMMIT} refs/heads/feat/initial-app\n")
    assert read_build_info(tmp_path).commit == "b9602de"


def test_reads_a_worktree_whose_git_is_a_pointer_file(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    common = make_repo(main)
    (common / "refs" / "heads" / "feat" / "live").write_text(COMMIT + "\n")
    worktree_git = common / "worktrees" / "session"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/feat/live\n")
    (worktree_git / "commondir").write_text("../..\n")
    checkout = tmp_path / "session"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {worktree_git}\n")
    info = read_build_info(checkout)
    assert (info.branch, info.commit) == ("feat/live", "b9602de")


def test_detached_head(tmp_path):
    make_repo(tmp_path, head=COMMIT + "\n")
    info = read_build_info(tmp_path)
    assert (info.branch, info.commit) == ("detached", "b9602de")


def test_no_repo_or_broken_files_give_none(tmp_path):
    assert read_build_info(tmp_path) is None
    make_repo(tmp_path)  # HEAD points at a branch with no ref anywhere
    assert read_build_info(tmp_path) is None
