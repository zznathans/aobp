from app.services import manufacturing

TRITANIUM_TYPE_ID = 34
PYERITE_TYPE_ID = 35
PRODUCT_TYPE_ID = 587


def test_material_quantity_per_run_rounds_up_and_applies_efficiency() -> None:
    assert manufacturing.material_quantity_per_run(100, 0) == 100
    assert manufacturing.material_quantity_per_run(100, 10) == 90
    # ceil(10 * 0.99) = 10 -> min-1 floor never kicks in here, but a material efficiency
    # so high relative to a small base quantity would still need at least 1 unit.
    assert manufacturing.material_quantity_per_run(1, 10) == 1


def test_compute_material_requirements_scales_by_runs_and_tracks_missing() -> None:
    materials = [{"type_id": TRITANIUM_TYPE_ID, "quantity": 100}]
    requirements = manufacturing.compute_material_requirements(
        materials,
        material_efficiency=10,
        runs=3,
        on_site_totals={TRITANIUM_TYPE_ID: 100},
        global_totals={TRITANIUM_TYPE_ID: 500},
    )

    assert len(requirements) == 1
    requirement = requirements[0]
    # 100 * 0.9 = 90/run * 3 runs = 270 needed
    assert requirement.per_run_needed == 90
    assert requirement.needed == 270
    assert requirement.on_site_have == 100
    assert requirement.on_site_missing == 170
    assert requirement.global_have == 500
    assert requirement.global_missing == 0


def test_compute_buildable_is_limited_by_scarcest_material() -> None:
    materials = [
        {"type_id": TRITANIUM_TYPE_ID, "quantity": 10},
        {"type_id": PYERITE_TYPE_ID, "quantity": 5},
    ]
    requirements = manufacturing.compute_material_requirements(
        materials,
        material_efficiency=0,
        runs=1,
        on_site_totals={TRITANIUM_TYPE_ID: 25, PYERITE_TYPE_ID: 6},
        global_totals={TRITANIUM_TYPE_ID: 100, PYERITE_TYPE_ID: 100},
    )

    on_site_buildable, global_buildable = manufacturing.compute_buildable(requirements)

    # Tritanium allows 2 runs on-site, Pyrite only allows 1 -> bottlenecked at 1.
    assert on_site_buildable == 1
    # Globally both materials are abundant -> bottlenecked by Tritanium's 100/10 = 10.
    assert global_buildable == 10


def test_compute_buildable_returns_zero_for_no_materials() -> None:
    assert manufacturing.compute_buildable([]) == (0, 0)


def test_compute_cost_output_profit_scales_by_runs() -> None:
    materials = [{"type_id": TRITANIUM_TYPE_ID, "quantity": 10}]
    price_by_type_id = {
        TRITANIUM_TYPE_ID: {"average_price": 5.0},
        PRODUCT_TYPE_ID: {"average_price": 100.0},
    }

    cost, output, profit = manufacturing.compute_cost_output_profit(
        materials,
        product_type_id=PRODUCT_TYPE_ID,
        product_quantity=1,
        runs=2,
        material_efficiency=0,
        price_by_type_id=price_by_type_id,
    )

    # 10 Tritanium/run * 5 ISK * 2 runs = 100 ISK cost; output = 1 * 100 ISK * 2 runs = 200 ISK.
    assert cost == 100.0
    assert output == 200.0
    assert profit == 100.0


def test_compute_cost_output_profit_without_a_product_has_no_output() -> None:
    materials = [{"type_id": TRITANIUM_TYPE_ID, "quantity": 10}]

    cost, output, profit = manufacturing.compute_cost_output_profit(
        materials,
        product_type_id=None,
        product_quantity=1,
        runs=1,
        material_efficiency=0,
        price_by_type_id={},
    )

    assert cost == 0.0
    assert output == 0.0
    assert profit == 0.0
