"""生成宝塔上传包与 GitHub 源码包；明确白名单，不带密钥、运行数据和依赖目录。

调用：python -B scripts/package_upload.py
不启动后端，不读取 .env，不打包正在写入的数据库。输出每次放入新的时间目录。
"""
from datetime import datetime
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {".gitignore", ".dockerignore", ".env.example", ".oxlintrc.json", "README.md",
              "index.html", "package.json", "package-lock.json", "vite.config.js",
              "compose.yaml", "compose.https.yaml", "compose.pages.yaml", "compose.baota.yaml"}
TREES = {"src", "public", "backend", "deploy", "docs", "scripts", ".github"}
EXTENSIONS = {".py", ".js", ".jsx", ".css", ".json", ".mjs", ".md", ".txt", ".yaml", ".yml",
              ".sh", ".ps1", ".example", ".conf", ".jpg", ".jpeg", ".png", ".svg", ".webp", ".ico"}
TEXT_EXTENSIONS = EXTENSIONS - {".jpg", ".jpeg", ".png", ".webp", ".ico"}
SECRETS = re.compile(rb"\b(?:sk-|pat_|cztei_|ghp_)[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")


def allowed(path):
    rel = path.relative_to(ROOT)
    if path.is_symlink() or not path.is_file():
        return False
    if any(part.startswith("runtime") or part in {"__pycache__", "node_modules", ".git", "verification",
               "server-data", "backups", "release"} for part in rel.parts):
        return False
    if rel.as_posix() in ROOT_FILES:
        return True
    if rel.parts[0] not in TREES:
        return False
    if (path.name.startswith(".env") or ".env" in path.name) and not path.name.endswith(".example"):
        return False
    return path.suffix in EXTENSIONS or path.name.startswith(("Dockerfile", "Caddyfile"))


def content(path):
    data = path.read_bytes()
    is_text = path.suffix in TEXT_EXTENSIONS or path.name.startswith(("Dockerfile", "Caddyfile", "."))
    if is_text:
        if SECRETS.search(data):
            raise RuntimeError(f"疑似密钥，请先检查文件（不输出内容）：{path.relative_to(ROOT)}")
        # Windows 编辑过的 shell 脚本也以 LF、无 BOM 进入压缩包，避免 Linux 报 ^M。
        if path.suffix == ".sh":
            data = data.decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8")
    return data


def write_archive(destination, prefix, paths, extra=None):
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.writestr(f"{prefix}/{path.relative_to(ROOT).as_posix()}", content(path))
        for name, data in (extra or {}).items():
            archive.writestr(f"{prefix}/{name}", data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(not name.endswith((".env", ".sqlite3", ".sqlite", ".pyc")) for name in archive.namelist())


def main():
    # rglob 只对已知源码根目录执行，目录过滤让运行文件无法进入候选集。
    paths = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for name in TREES:
        # walk 时跳过运行目录，避免扫描大量用户原图和数据库。
        for current, directories, files in (ROOT / name).walk():
            directories[:] = [d for d in directories if not d.startswith("runtime") and d not in
                {"__pycache__", "node_modules", "verification", ".git", "release", "server-data", "backups"}]
            paths.extend(p for file in files if allowed(p := current / file))
    paths = sorted(set(paths))
    output = ROOT / "release" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    needed = {".dockerignore", "compose.baota.yaml", "deploy/Dockerfile.api", "deploy/backend.baota.env.example",
              "deploy/baota-proxy.conf", "deploy/baota-init.sh", "deploy/baota-inspect.sh", "docs/baota-upload-steps.md",
              "docs/github-pages-cloud-tutorial.md", "docs/github-docker-deployment-tutorial.md",
              "deploy/enable-pages-origin.sh", "docs/pages-auto-connect.md"}
    backend = [p for p in paths if p.relative_to(ROOT).as_posix() in needed or
               (p.relative_to(ROOT).parts[0] == "backend" and "tests" not in p.parts)]
    required = {"backend/app.py", "backend/requirements.txt", "backend/zhishiku/requirements.txt"} | needed
    assert required.issubset({p.relative_to(ROOT).as_posix() for p in backend})
    start = ("宝塔上传包：服务器 8.138.30.176\n"
             "上传到 /www 后解压，会产生 /www/kuajing-next；不要覆盖 /www/wwwroot/aliyun-deploy。\n"
             "先在宝塔终端执行：\ncd /www/kuajing-next\nbash deploy/baota-inspect.sh\n"
             "再读 docs/baota-upload-steps.md，初始化、填 backend.env、构建、迁移、启动。\n"
             "本包不含真实密钥、知识库数据和历史图片；旧 db/.env/容器先保留。\n"
             "仅 compose.baota.yaml 用于这次宝塔部署，其他教程的 Caddy 命令不要混用。\n")
    write_archive(output / "kuajing-backend.zip", "kuajing-next", backend, {"START-HERE.txt": start.encode("utf-8")})
    write_archive(output / "kuajing-github-source.zip", "kuajing-source", paths)
    lines = []
    for path in sorted(output.glob("*.zip")):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        print(f"{path.name}: {path.stat().st_size / 1024 / 1024:.2f} MiB")
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "操作说明.md").write_bytes((ROOT / "docs/baota-upload-steps.md").read_bytes())
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
