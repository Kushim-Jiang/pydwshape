/* wd_font.h — raw-sfnt font driver for the Wine DWrite shaping port.
 * Parses a font file's bytes directly (table directory, cmap, head, hmtx) so
 * the shaping engine needs no FreeType and no OS APIs. Cross-platform. */
#ifndef WD_FONT_H
#define WD_FONT_H

#include <stddef.h>
#include <stdint.h>

struct wd_font;

/* Open a font from an in-memory byte blob (TTF/OTF, or a TTC collection in
 * which case face index 0 is used). The blob must stay alive while the font
 * is used. Returns NULL on failure. */
struct wd_font *wd_font_open(const uint8_t *data, size_t size);
void wd_font_close(struct wd_font *f);

/* 'tag' is a host-order OpenType 4CC, e.g. 0x47535542 for "GSUB". Returns a
 * pointer to the table bytes and its size, or NULL/0 if absent. */
const uint8_t *wd_font_table(struct wd_font *f, uint32_t tag, uint32_t *size);

uint16_t wd_font_upem(struct wd_font *f);
uint16_t wd_font_glyph(struct wd_font *f, uint32_t codepoint);
int      wd_font_has_glyph(struct wd_font *f, uint32_t codepoint);
/* Design-unit advance width for a glyph (hmtx), 0 if missing. */
uint16_t wd_font_advance(struct wd_font *f, uint16_t gid);

#endif /* WD_FONT_H */
