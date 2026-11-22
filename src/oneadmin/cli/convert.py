"""``oneadmin convert sqladmin FILE``: rewrite sqladmin ``ModelView`` classes as ``ModelAdmin``.

A starting point, not a guarantee. Options with a direct equivalent are translated;
``can_create``/``can_edit``/``can_delete`` become permission hooks; everything else is kept
as a ``TODO(oneadmin)`` comment with the original source, so nothing is lost silently. The
output is a new module and the input file is never modified.

| sqladmin                         | OneAdmin                                   |
|----------------------------------|--------------------------------------------|
| ``class X(ModelView, model=M)``  | ``@admin.register(M) class X(ModelAdmin[M])`` |
| ``column_list``                  | ``list_display``                           |
| ``column_searchable_list``       | ``search_fields``                          |
| ``column_sortable_list``         | ``sortable_fields``                        |
| ``column_filters``               | ``list_filter`` (the filtered column)      |
| ``column_default_sort``          | ``ordering``                               |
| ``column_details_exclude_list``  | ``exclude``                                |
| ``form_excluded_columns``        | ``readonly_fields``                        |
| ``column_labels``                | ``labels``                                 |
| ``page_size``                    | ``list_per_page``                          |
| ``name`` / ``name_plural``       | ``verbose_name`` / ``verbose_name_plural`` |
| ``can_create/edit/delete=False`` | ``has_add/change/delete_permission``       |
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

_RENAMES = {
    "column_list": "list_display",
    "column_searchable_list": "search_fields",
    "column_sortable_list": "sortable_fields",
    "column_details_exclude_list": "exclude",
    "form_excluded_columns": "readonly_fields",
    "column_labels": "labels",
    "page_size": "list_per_page",
    "name": "verbose_name",
    "name_plural": "verbose_name_plural",
}
_PERMISSIONS = {
    "can_create": ("has_add_permission", "self, ctx"),
    "can_edit": ("has_change_permission", "self, ctx, obj=None"),
    "can_delete": ("has_delete_permission", "self, ctx, obj=None"),
}
_IGNORED = {"icon", "category", "identity", "can_view_details", "can_export", "column_details_list"}


@dataclass
class Conversion:
    source: str
    converted: list[str] = field(default_factory=list)
    """Names of the classes that were converted."""
    todos: int = 0


def convert_sqladmin(source: str) -> Conversion:
    """Convert every ``ModelView`` subclass in ``source``."""
    tree = ast.parse(source)
    result = Conversion(source="")
    imports: list[str] = []
    blocks: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom) and not _is_sqladmin_import(node):
            imports.append(_segment(source, node))
        elif isinstance(node, ast.ClassDef) and _model_of(node) is not None:
            text, todos = _convert_class(source, node)
            blocks.append(text)
            result.converted.append(node.name)
            result.todos += todos
    header = [
        '"""Admin classes migrated from SQLAdmin by `oneadmin convert sqladmin`.',
        "",
        "Review every TODO(oneadmin) comment, then delete this note.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import os",
        "",
        "from oneadmin import AdminSite, ModelAdmin",
        *imports,
        "",
        "# TODO(oneadmin): use your app's async_sessionmaker (sqladmin took an engine).",
        "from app.database import async_session_maker",
        "",
        "admin = AdminSite(",
        "    session_factory=async_session_maker,",
        '    secret_key=os.environ.get("ONEADMIN_SECRET_KEY"),',
        ")",
    ]
    body = "\n\n\n".join(blocks)
    result.source = "\n".join(header) + ("\n\n\n" + body if body else "") + "\n"
    return result


def _convert_class(source: str, node: ast.ClassDef) -> tuple[str, int]:
    model = _segment(source, _model_of(node))  # type: ignore[arg-type]
    lines = [f"@admin.register({model})", f"class {node.name}(ModelAdmin[{model}]):"]
    todos = 0
    body: list[str] = []
    doc = ast.get_docstring(node)
    if doc:
        body.append(f'    """{doc}"""')
    for stmt in node.body:
        if _is_docstring(stmt):
            continue
        target, value = _assignment(stmt)
        if target is None or value is None:
            body.append(_todo("custom code; port it to OneAdmin hooks by hand", source, stmt))
            todos += 1
            continue
        if target in _RENAMES:
            body.append(f"    {_RENAMES[target]} = {_as_tuple(source, value)}")
        elif target == "column_default_sort":
            ordering = _ordering(source, value)
            if ordering is None:
                body.append(_todo("unrecognised column_default_sort", source, stmt))
                todos += 1
            else:
                body.append(f"    ordering = {ordering}")
        elif target == "column_filters":
            body.append(f"    list_filter = {_filters(source, value)}")
        elif target in _PERMISSIONS and isinstance(value, ast.Constant):
            if value.value is False:
                method, params = _PERMISSIONS[target]
                body += ["", f"    async def {method}({params}):", "        return False", ""]
        elif target == "column_exclude_list":
            body.append(
                _todo(
                    "hidden from the list only: leave these names out of list_display", source, stmt
                )
            )
            todos += 1
        elif target in _IGNORED:
            continue
        else:
            body.append(_todo(f"no direct equivalent for sqladmin's {target}", source, stmt))
            todos += 1
    lines += _tidy(body) or ["    pass"]
    return "\n".join(lines), todos


# ---- helpers -------------------------------------------------------------------------------
def _model_of(node: ast.ClassDef) -> ast.expr | None:
    if not any(_name(b).endswith("ModelView") for b in node.bases):
        return None
    return next((k.value for k in node.keywords if k.arg == "model"), None)


def _name(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return f"{_name(expr.value)}.{expr.attr}"
    return ""


def _is_sqladmin_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "sqladmin"
    return any(alias.name.split(".")[0] == "sqladmin" for alias in node.names)


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _assignment(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    if (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
    ):
        return stmt.targets[0].id, stmt.value
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
        return stmt.target.id, stmt.value
    return None, None


def _segment(source: str, node: ast.AST) -> str:
    text = ast.get_source_segment(source, node)
    return text if text is not None else ast.unparse(node)


def _as_tuple(source: str, value: ast.expr) -> str:
    """Lists become tuples (OneAdmin options are immutable sequences)."""
    if isinstance(value, ast.List):
        items = [_segment(source, e) for e in value.elts]
        return f"({', '.join(items)}{',' if len(items) == 1 else ''})"
    return _segment(source, value)


def _ordering(source: str, value: ast.expr) -> str | None:
    """``"id"``, ``Model.id``, ``("id", True)`` or a list of those (True = descending)."""
    pairs = value.elts if isinstance(value, ast.List) else [value]
    out: list[str] = []
    for item in pairs:
        column, descending = item, False
        if isinstance(item, ast.Tuple) and len(item.elts) == 2:
            column = item.elts[0]
            flag = item.elts[1]
            if not isinstance(flag, ast.Constant) or not isinstance(flag.value, bool):
                return None
            descending = flag.value
        if isinstance(column, ast.Constant) and isinstance(column.value, str):
            out.append(repr(("-" if descending else "") + column.value).replace("'", '"'))
        elif isinstance(column, ast.Attribute | ast.Name):
            text = _segment(source, column)
            out.append(f"{text}.desc()" if descending else text)
        else:
            return None
    return f"({', '.join(out)}{',' if len(out) == 1 else ''})"


def _filters(source: str, value: ast.expr) -> str:
    """sqladmin filters are columns or filter objects (``BooleanFilter(User.active)``)."""
    items = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
    out = []
    for item in items:
        if isinstance(item, ast.Call) and item.args:
            out.append(_segment(source, item.args[0]))
        else:
            out.append(_segment(source, item))
    return f"({', '.join(out)}{',' if len(out) == 1 else ''})"


def _todo(reason: str, source: str, stmt: ast.stmt) -> str:
    original = _segment(source, stmt).splitlines()
    return "\n".join(
        [f"    # TODO(oneadmin): {reason}:", *(f"    #   {line}" for line in original)]
    )


def _tidy(lines: list[str]) -> list[str]:
    """Drop blank lines at the edges and doubled blank lines."""
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out
