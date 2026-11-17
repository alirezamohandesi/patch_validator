/* cjson_cli — a minimal command-line front end for the cJSON library.
 *
 * The validator needs a target that reads one input from a file or from
 * standard input and terminates with a documented exit code.  cJSON is a
 * library, so this harness supplies that interface and nothing else: it holds
 * no parsing logic of its own, and every decision it reports comes from the
 * library under test.
 *
 * Two details matter for the validation and are deliberate:
 *
 *   1. The input buffer is allocated at exactly the input length and is NOT
 *      NUL terminated, and cJSON_ParseWithLength() is used rather than
 *      cJSON_Parse().  That is the documented API for parsing a bounded
 *      buffer, and it is the only way a read past the end of the buffer can
 *      be observed at all: with a NUL terminated buffer the sentinel hides
 *      the defect.
 *   2. Output is produced with cJSON_PrintUnformatted(), whose format is
 *      documented and stable, so the expected output for an input can be
 *      derived from the JSON grammar rather than from a particular build.
 *
 * Usage:
 *     cjson_cli FILE
 *     cjson_cli -          (read standard input)
 *
 * Exit codes:
 *     0   the input is valid JSON; the canonical form is on stdout
 *     1   the input is not valid JSON
 *     2   the input could not be read, or the output could not be produced
 *     64  wrong number of arguments
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

#define RC_OK 0
#define RC_INVALID 1
#define RC_IO 2
#define RC_USAGE 64

#define MAX_INPUT_BYTES (1u << 20)

static int read_all(FILE *in, char **out_data, size_t *out_len)
{
    size_t capacity = 4096;
    size_t length = 0;
    char *buffer = malloc(capacity);

    if (buffer == NULL) {
        return -1;
    }

    for (;;) {
        if (length == capacity) {
            if (capacity >= MAX_INPUT_BYTES) {
                break;
            }
            capacity *= 2;
            char *grown = realloc(buffer, capacity);
            if (grown == NULL) {
                free(buffer);
                return -1;
            }
            buffer = grown;
        }

        size_t got = fread(buffer + length, 1, capacity - length, in);
        length += got;
        if (got == 0) {
            break;
        }
    }

    /* Shrink to exactly the input length.  An over-allocated buffer would
     * leave slack that a read past the end could land in unnoticed. */
    char *exact = malloc(length == 0 ? 1 : length);
    if (exact == NULL) {
        free(buffer);
        return -1;
    }
    memcpy(exact, buffer, length);
    free(buffer);

    *out_data = exact;
    *out_len = length;
    return 0;
}

int main(int argc, char **argv)
{
    FILE *in = stdin;

    if (argc > 2) {
        fprintf(stderr, "usage: cjson_cli [FILE|-]\n");
        return RC_USAGE;
    }

    if (argc == 2 && strcmp(argv[1], "-") != 0) {
        in = fopen(argv[1], "rb");
        if (in == NULL) {
            fprintf(stderr, "error: cannot open '%s'\n", argv[1]);
            return RC_IO;
        }
    }

    char *data = NULL;
    size_t length = 0;

    if (read_all(in, &data, &length) != 0) {
        fprintf(stderr, "error: cannot read input\n");
        if (in != stdin) {
            fclose(in);
        }
        return RC_IO;
    }

    if (in != stdin) {
        fclose(in);
    }

    cJSON *item = cJSON_ParseWithLength(data, length);
    free(data);

    if (item == NULL) {
        fprintf(stderr, "error: invalid json\n");
        return RC_INVALID;
    }

    char *printed = cJSON_PrintUnformatted(item);
    cJSON_Delete(item);

    if (printed == NULL) {
        fprintf(stderr, "error: cannot serialise\n");
        return RC_IO;
    }

    printf("%s\n", printed);
    free(printed);
    fflush(stdout);
    return RC_OK;
}
