/* wd_script.h — Unicode script auto-detection for the Wine DWrite port.
 * Mirrors what DWriteCore's analyzer does when no script is supplied: scan the
 * text, find the dominant non-Common/Inherited Unicode script, and map it to
 * the OpenType script tag(s) to request from the font (mong, arab, latn, ...).
 * Shaping stays script-agnostic (universal joining shaper); this only picks
 * which GSUB/GPOS script table of the font to use. */
#ifndef WD_SCRIPT_H
#define WD_SCRIPT_H

#include <stdint.h>

/* Dominant Unicode script of `text` (UTF-16 code units). Returns a value from
 * scripts.h's `unicode_script_id` (Script_Unknown..). */
unsigned wd_detect_script(const uint16_t *text, unsigned len);

/* Map a unicode_script_id to up to 2 OpenType script tags (LE numeric 4CC,
 * primary first, secondary second for legacy Indic tags such as dev2/beng),
 * zero-terminated (tags[0]==0 when unknown). */
void wd_script_tags(unsigned script_id, uint32_t tags[3]);

#endif /* WD_SCRIPT_H */
