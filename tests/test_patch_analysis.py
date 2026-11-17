"""Diff parsing, function mapping and correlation grading."""

from __future__ import annotations

import pytest

from patch_validator.analysis.cfunctions import extract_functions, function_at
from patch_validator.analysis.diffparse import parse_patch

MODIFICATION = """diff --git a/src/record.c b/src/record.c
index 1111111..2222222 100644
--- a/src/record.c
+++ b/src/record.c
@@ -10,7 +10,7 @@ static int copy_payload(char *dst, size_t size, const uint8_t *src, size_t len)
 {
-    (void)size;
-    if (len > MAX_WIRE) {
+    if (len + 1 > size) {
         return -1;
     }
     memcpy(dst, src, len);
"""

PURE_INSERTION = """diff --git a/src/record.c b/src/record.c
index 1111111..2222222 100644
--- a/src/record.c
+++ b/src/record.c
@@ -27,6 +27,12 @@ static int handle_text(const uint8_t *payload, size_t len)
 {
     char buf[32];

+    if (len >= 32) {
+        fprintf(stderr, "too long\\n");
+        return RC_TOO_LONG;
+    }
+
+
     if (copy_payload(buf, sizeof(buf), payload, len) != 0) {
         return RC_TOO_LONG;
     }
"""

MULTI_FILE = """diff --git a/a.c b/a.c
--- a/a.c
+++ b/a.c
@@ -1,3 +1,3 @@
-int old(void) { return 1; }
+int new(void) { return 2; }
 int keep(void);
diff --git a/b.h b/b.h
new file mode 100644
--- /dev/null
+++ b/b.h
@@ -0,0 +1,2 @@
+#define X 1
+#define Y 2
diff --git a/gone.c b/gone.c
deleted file mode 100644
--- a/gone.c
+++ /dev/null
@@ -1,2 +0,0 @@
-void gone(void) {}
-
"""


class TestDiffParsing:
    def test_modification_records_both_sides(self):
        diff = parse_patch(MODIFICATION)
        hunk = diff.files[0].hunks[0]
        assert hunk.removed_lines == (11, 12)
        assert hunk.added_lines == (11,)

    def test_old_and_new_line_numbers_are_tracked_separately(self):
        hunk = parse_patch(PURE_INSERTION).files[0].hunks[0]
        assert hunk.added_lines == (30, 31, 32, 33, 34, 35)
        assert hunk.removed_lines == ()

    def test_a_pure_insertion_still_marks_the_old_side(self):
        """Without this, a fault on the base build could never be tied to a
        patch that only adds code."""
        hunk = parse_patch(PURE_INSERTION).files[0].hunks[0]
        assert hunk.insertion_points == (30,)
        assert hunk.changed_lines("old") == {30}
        assert hunk.touches(30, side="old")
        assert not hunk.touches(29, side="old")

    def test_a_deletion_marks_the_new_side(self):
        hunk = parse_patch(MODIFICATION).files[0].hunks[0]
        assert hunk.deletion_points

    def test_file_statuses(self):
        diff = parse_patch(MULTI_FILE)
        statuses = {entry.path: entry.status for entry in diff.files}
        assert statuses == {"a.c": "modified", "b.h": "added", "gone.c": "deleted"}

    def test_lookup_by_path_and_by_basename(self):
        diff = parse_patch(MULTI_FILE)
        assert diff.file_for("a.c") is not None
        assert diff.file_for("nope.c") is None
        assert diff.file_by_basename("a.c") is not None

    def test_ambiguous_basenames_are_not_matched(self):
        ambiguous = """diff --git a/one/x.c b/one/x.c
--- a/one/x.c
+++ b/one/x.c
@@ -1 +1 @@
-a
+b
diff --git a/two/x.c b/two/x.c
--- a/two/x.c
+++ b/two/x.c
@@ -1 +1 @@
-c
+d
"""
        assert parse_patch(ambiguous).file_by_basename("x.c") is None

    def test_empty_diff(self):
        diff = parse_patch("")
        assert diff.is_empty
        assert diff.summary() == "0 file(s), 0 hunk(s)"

    def test_summary_counts(self):
        assert parse_patch(MULTI_FILE).summary() == "3 file(s), 3 hunk(s)"


SOURCE = """\
#include <stdio.h>

#define WRAP(x) do { x; } while (0)

struct config { int a; };
static const struct config DEFAULTS = { .a = 1 };

static int helper(int a)
{
    if (a > 0) { return a; }
    return 0;
}

int
split_signature(int a,
                int b)
{
    const char *s = "a brace } in a string";
    /* and { one } in a comment */
    return helper(a) + b;
}
"""


class TestFunctionMapping:
    def test_functions_and_their_spans(self):
        functions = {f.name: (f.start_line, f.end_line) for f in extract_functions(SOURCE)}
        assert functions["helper"] == (8, 12)
        assert functions["split_signature"] == (14, 21)

    def test_a_function_like_macro_is_not_a_function(self):
        assert "WRAP" not in {f.name for f in extract_functions(SOURCE)}

    def test_a_struct_initialiser_is_not_a_function(self):
        assert "DEFAULTS" not in {f.name for f in extract_functions(SOURCE)}
        assert "config" not in {f.name for f in extract_functions(SOURCE)}

    def test_braces_inside_literals_and_comments_do_not_shift_the_span(self):
        found = function_at(extract_functions(SOURCE), 20)
        assert found is not None and found.name == "split_signature"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [(9, "helper"), (11, "helper"), (17, "split_signature"), (2, None)],
    )
    def test_line_to_function(self, line, expected):
        found = function_at(extract_functions(SOURCE), line)
        assert (found.name if found else None) == expected

    def test_a_multi_line_signature_starts_at_its_first_line(self):
        found = function_at(extract_functions(SOURCE), 14)
        assert found is not None and found.name == "split_signature"
