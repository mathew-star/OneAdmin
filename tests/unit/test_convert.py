"""``oneadmin convert sqladmin``: options mapped, nothing dropped silently, output runs."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from oneadmin.cli import Console, main
from oneadmin.cli.convert import convert_sqladmin

SQLADMIN = '''
from sqladmin import Admin, ModelView
from sqladmin.filters import BooleanFilter
from app.models import User, Post


class UserAdmin(ModelView, model=User):
    """Shop customers."""

    name = "Customer"
    name_plural = "Customers"
    icon = "fa-solid fa-user"
    column_list = [User.id, User.email, "full_name"]
    column_searchable_list = [User.email]
    column_sortable_list = [User.id]
    column_default_sort = [(User.created_at, True), "id"]
    column_filters = [BooleanFilter(User.is_active)]
    column_labels = {User.email: "E-mail"}
    form_excluded_columns = [User.created_at]
    column_details_exclude_list = [User.password_hash]
    page_size = 25
    can_delete = False
    column_formatters = {User.email: lambda m, a: m.email.lower()}

    async def on_model_change(self, data, model, is_created, request):
        pass


class PostAdmin(ModelView, model=Post):
    column_list = [Post.id]
    column_exclude_list = [Post.body]


admin = Admin(app, engine)
admin.add_view(UserAdmin)
'''


def test_options_are_mapped() -> None:
    result = convert_sqladmin(SQLADMIN)
    out = result.source
    assert result.converted == ["UserAdmin", "PostAdmin"]
    for line in (
        "@admin.register(User)",
        "class UserAdmin(ModelAdmin[User]):",
        '    """Shop customers."""',
        '    verbose_name = "Customer"',
        '    list_display = (User.id, User.email, "full_name")',
        "    search_fields = (User.email,)",
        "    sortable_fields = (User.id,)",
        '    ordering = (User.created_at.desc(), "id")',
        "    list_filter = (User.is_active,)",
        '    labels = {User.email: "E-mail"}',
        "    readonly_fields = (User.created_at,)",
        "    exclude = (User.password_hash,)",
        "    list_per_page = 25",
        "    async def has_delete_permission(self, ctx, obj=None):",
        "from app.models import User, Post",
    ):
        assert line in out, line
    assert "from sqladmin" not in out
    assert "import sqladmin" not in out
    assert "icon" not in out


def test_untranslatable_code_is_kept_as_todo() -> None:
    result = convert_sqladmin(SQLADMIN)
    assert result.todos == 3  # column_formatters, on_model_change, column_exclude_list
    assert (
        "# TODO(oneadmin): no direct equivalent for sqladmin's column_formatters:" in result.source
    )
    assert "#   async def on_model_change(self, data, model, is_created, request):" in result.source
    assert "leave these names out of list_display" in result.source


def test_output_is_valid_python() -> None:
    compile(convert_sqladmin(SQLADMIN).source, "admin.py", "exec")


def run(*argv: str) -> tuple[int, str, str]:
    con = Console(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
    code = main(list(argv), console=con)
    return code, con.stdout.getvalue(), con.stderr.getvalue()  # type: ignore[attr-defined]


def test_cli(tmp_path: Path) -> None:
    src = tmp_path / "views.py"
    src.write_text(SQLADMIN)
    code, out, err = run("convert", "sqladmin", str(src))
    assert code == 0
    assert "class UserAdmin(ModelAdmin[User]):" in out
    assert "Converted 2 class(es): UserAdmin, PostAdmin. 3 TODO(oneadmin) note(s)" in err

    target = tmp_path / "admin.py"
    assert run("convert", "sqladmin", str(src), "--output", str(target))[0] == 0
    assert target.read_text().startswith('"""Admin classes migrated from SQLAdmin')
    assert "must differ" in run("convert", "sqladmin", str(src), "--output", str(src))[2]


@pytest.mark.parametrize(
    ("content", "message"),
    [("x = 1\n", "No sqladmin ModelView classes found"), ("def (:\n", "isn't valid Python")],
)
def test_cli_errors(tmp_path: Path, content: str, message: str) -> None:
    src = tmp_path / "views.py"
    src.write_text(content)
    code, _, err = run("convert", "sqladmin", str(src))
    assert code == 1
    assert message in err
