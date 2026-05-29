from workbook_cli.dates import day_name_from_registration_date


def test_day_name_from_registration_date() -> None:
    assert day_name_from_registration_date("2026-05-25T00:00:00.000Z") == "Mon"
    assert day_name_from_registration_date("2026-05-29T00:00:00.000Z") == "Fri"
    assert day_name_from_registration_date("") is None
