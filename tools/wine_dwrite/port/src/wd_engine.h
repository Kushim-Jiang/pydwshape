/* wd_engine.h — public C API for the Wine DWrite shaping port.
 * Drives the ported GSUB/GPOS engine exactly like Wine's dwrite analyzer:
 *   GetGlyphs  = shape_get_glyphs  (nominal cmap -> GSUB lookups)
 *   placements = shape_get_positions (GPOS lookups over pre-filled hmtx advances)
 * All results are in font design units (advances) when emsize == upem. */
#ifndef WD_ENGINE_H
#define WD_ENGINE_H

#include <stdint.h>

/* one shaped glyph (final state) */
typedef struct wd_glyph
{
    uint16_t gid;
    uint32_t cluster;      /* text (UTF-16 unit) index of the cluster start */
    float    ax;           /* advance x (design units) */
    float    ay;
    float    dx;           /* placement offset x (design units) */
    float    dy;
} wd_glyph;

typedef struct wd_shape_opts
{
    const uint8_t *font;       /* font bytes (must outlive the call) */
    size_t         font_size;
    const uint16_t *text;      /* UTF-16 text */
    unsigned       text_len;   /* number of UTF-16 code units */
    unsigned       script_id;  /* unicode_script_id from scripts.h (Script_Mongolian etc.) */
    uint32_t       script_tag; /* primary OpenType script tag, e.g. 'mong'; 0 = font default */
    uint32_t       script_tag2; /* secondary tag (legacy Indic like 'deva'); 0 = none */
    int            rtl;        /* visual order handling */
    int            want_positions; /* run GPOS (advances/offsets) as well */
} wd_shape_opts;

/* Shape and fill out[0..*n). Returns 0 on success, -1 on error, -2 if the
 * run exceeded max_out (caller should retry with a bigger buffer). */
int wd_shape(const wd_shape_opts *opts, wd_glyph *out, unsigned max_out, unsigned *n);

/* Per-lookup trace (valid until the next wd_shape call). Each stage is a
 * snapshot of the glyph run taken just BEFORE that lookup applied, plus one
 * seq==0 "nominal cmap" snapshot before any GSUB lookup. table: 0 = GSUB,
 * 1 = GPOS. */
typedef struct wd_stage_view
{
    unsigned        table;
    unsigned        seq;    /* 0 = nominal baseline, else 1-based lookup */
    unsigned        count;
    const uint16_t *glyphs;
} wd_stage_view;

unsigned wd_trace_count(void);
int      wd_trace_get(unsigned i, wd_stage_view *v);

#endif /* WD_ENGINE_H */
