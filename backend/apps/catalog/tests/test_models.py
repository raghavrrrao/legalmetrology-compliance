"""Category hierarchy and product identity."""

import pytest

from apps.catalog.models import Product, ProductCategory

pytestmark = pytest.mark.django_db


def test_ancestry_includes_self_and_parents(category):
    child = ProductCategory.objects.create(
        code="biscuits", name="Biscuits", parent=category
    )
    grandchild = ProductCategory.objects.create(
        code="cream-biscuits", name="Cream biscuits", parent=child
    )

    assert grandchild.ancestry_codes() == [
        "cream-biscuits",
        "biscuits",
        "packaged-food",
    ]


def test_ancestry_of_a_root_category(category):
    assert category.ancestry_codes() == ["packaged-food"]


def test_ancestry_survives_a_cyclic_parent_chain(category):
    """The database does not prevent a cycle, so the walk must not hang."""
    child = ProductCategory.objects.create(
        code="child", name="Child", parent=category
    )
    category.parent = child
    category.save()

    codes = child.ancestry_codes()

    assert set(codes) == {"child", "packaged-food"}
    assert len(codes) == 2


def test_product_without_a_category_matches_no_codes(db):
    product = Product.objects.create(name="Unidentified")
    assert product.applicable_category_codes == []


def test_product_inherits_its_category_ancestry(product, category):
    assert product.applicable_category_codes == ["packaged-food"]


def test_product_uses_a_uuid_primary_key(product):
    """IDs appear in URLs; sequential integers would allow enumeration."""
    import uuid

    assert isinstance(product.pk, uuid.UUID)


def test_category_code_is_unique(category):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        ProductCategory.objects.create(code="packaged-food", name="Duplicate")
