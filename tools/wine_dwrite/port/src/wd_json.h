/* wd_json.h — single-call JSON API for the Wine DWrite shaping port.
 * Returns a malloc'd babelsoft-style engine JSON string; caller frees with
 * wd_json_free(). Convenient for ctypes / other-language bindings. */
#ifndef WD_JSON_H
#define WD_JSON_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Shape `text` (UTF-16) with `font` bytes. Script is auto-detected from the
 * text when not overridden; pass tag1/tag2 (DWrite LE 4CC) to force, or 0 to
 * auto-detect. want_pos includes advances/offsets; want_trace includes the
 * per-lookup stages. Returns malloc'd JSON, or NULL on failure. */
char *wd_shape_json(const uint8_t *font, size_t font_size, const uint16_t *text,
        unsigned text_len, uint32_t tag1, uint32_t tag2,
        int rtl, int want_pos, int want_trace);

void wd_json_free(char *s);

#ifdef __cplusplus
}
#endif

#endif /* WD_JSON_H */
