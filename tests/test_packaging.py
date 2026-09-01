from game_engine.packaging import package_game


def test_package_enforces_limit(tmp_path):
    source = tmp_path / "game"
    source.mkdir()
    (source / "index.html").write_text("<canvas id=c></canvas><script>c.width=320</script>")
    report = package_game(source, tmp_path / "dist" / "game.zip", limit_bytes=1024)
    assert report.ok
    assert report.compressed_bytes <= 1024
