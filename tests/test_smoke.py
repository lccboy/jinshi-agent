def test_package_importable():
    import services.collector  # noqa: F401

    assert True
