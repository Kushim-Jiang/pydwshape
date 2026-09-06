/* wd_engine.c — orchestrator: drives the ported Wine DWrite GSUB/GPOS engine
 * exactly like Wine's analyzer does for GetGlyphs / GetGlyphPlacements. */

#include "dwrite_private.h"
#include "scripts.h"
#include "wd_font.h"
#include "wd_engine.h"

#include <stdlib.h>
#include <string.h>

/* --- font ops adapter (driver context = struct wd_font) ------------------ */

static void wd_grab_table(void *ctx, UINT32 tag, const BYTE **data, UINT32 *size, void **data_context)
{
    struct wd_font *f = (struct wd_font *)ctx;
    uint32_t sz = 0;
    const uint8_t *p = wd_font_table(f, tag, &sz);
    *data = p;
    *size = sz;
    *data_context = f; /* release is a no-op; font outlives the cache */
}
static void wd_release_table(void *ctx, void *data_context)
{
    (void)ctx;
    (void)data_context;
}
static UINT16 wd_get_upem(void *ctx)
{
    return wd_font_upem((struct wd_font *)ctx);
}
static BOOL wd_has_glyph(void *ctx, unsigned int cp)
{
    return wd_font_has_glyph((struct wd_font *)ctx, cp) ? TRUE : FALSE;
}
static UINT16 wd_get_glyph(void *ctx, unsigned int cp)
{
    return wd_font_glyph((struct wd_font *)ctx, cp);
}

static const struct shaping_font_ops wd_font_ops = {
    wd_grab_table,
    wd_release_table,
    wd_get_upem,
    wd_has_glyph,
    wd_get_glyph,
};

/* --- GSUB pass (mirrors dwrite GetGlyphs) --------------------------------- */

static HRESULT run_gsub(struct wd_font *f, struct scriptshaping_cache *cache,
        const WCHAR *text, unsigned text_len, unsigned script_id, uint32_t script_tag, uint32_t script_tag2,
        int rtl, unsigned cap,
        uint16_t **out_glyphs, DWRITE_SHAPING_GLYPH_PROPERTIES **out_props,
        struct shaping_glyph_info **out_ginfos, unsigned *out_count,
        DWRITE_SHAPING_TEXT_PROPERTIES **out_text_props, uint16_t **out_clustermap)
{
    struct scriptshaping_context ctx;
    uint16_t *glyphs;
    DWRITE_SHAPING_GLYPH_PROPERTIES *props;
    DWRITE_SHAPING_TEXT_PROPERTIES *tprops;
    struct shaping_glyph_info *ginfos;
    uint16_t *clustermap;
    WCHAR digits[11] = { 0 };
    unsigned int scripts[3];
    HRESULT hr;

    memset(&ctx, 0, sizeof(ctx));
    glyphs = (uint16_t *)calloc(cap, sizeof(*glyphs));
    props = (DWRITE_SHAPING_GLYPH_PROPERTIES *)calloc(cap, sizeof(*props));
    ginfos = (struct shaping_glyph_info *)calloc(cap, sizeof(*ginfos));
    tprops = text_len ? (DWRITE_SHAPING_TEXT_PROPERTIES *)calloc(text_len, sizeof(*tprops)) : NULL;
    clustermap = text_len ? (uint16_t *)calloc(text_len, sizeof(*clustermap)) : NULL;
    if (!glyphs || !props || !ginfos || (text_len && (!tprops || !clustermap)))
    {
        free(glyphs);
        free(props);
        free(ginfos);
        free(tprops);
        free(clustermap);
        return E_OUTOFMEMORY;
    }

    ctx.cache = cache;
    ctx.script = script_id > Script_LastId ? Script_Unknown : script_id;
    ctx.text = text;
    ctx.length = text_len;
    ctx.is_rtl = rtl ? TRUE : FALSE;
    ctx.is_sideways = FALSE;
    ctx.u.subst.glyphs = glyphs;
    ctx.u.subst.glyph_props = props;
    ctx.u.subst.text_props = tprops;
    ctx.u.subst.clustermap = clustermap;
    ctx.u.subst.max_glyph_count = cap;
    ctx.u.subst.capacity = cap;
    ctx.u.subst.digits = digits;
    ctx.language_tag = 0;
    ctx.glyph_infos = ginfos;
    ctx.table = &cache->gsub;

    scripts[0] = script_tag ? script_tag : 0;
    scripts[1] = script_tag2;
    scripts[2] = 0;
    hr = shape_get_glyphs(&ctx, scripts);

    /* engine may have reallocated the three arrays; read final pointers */
    *out_glyphs = ctx.u.subst.glyphs;
    *out_props = ctx.u.subst.glyph_props;
    *out_ginfos = ctx.glyph_infos;
    *out_count = ctx.glyph_count;
    *out_text_props = tprops;
    *out_clustermap = clustermap;
    return hr;
}

/* --- GPOS pass (mirrors dwrite GetGlyphPlacements) ------------------------ */

static void run_gpos(struct wd_font *f, struct scriptshaping_cache *cache,
        const WCHAR *text, unsigned text_len, unsigned script_id, uint32_t script_tag, uint32_t script_tag2,
        int rtl, unsigned count,
        const uint16_t *glyphs, const DWRITE_SHAPING_GLYPH_PROPERTIES *props,
        DWRITE_SHAPING_TEXT_PROPERTIES *tprops, const uint16_t *clustermap,
        unsigned upem, float *advances, DWRITE_GLYPH_OFFSET *offsets)
{
    struct scriptshaping_context ctx;
    struct shaping_glyph_info *ginfos;
    unsigned int scripts[3];
    unsigned i;

    memset(&ctx, 0, sizeof(ctx));
    for (i = 0; i < count; ++i)
    {
        advances[i] = props[i].isZeroWidthSpace ? 0.0f : (float)wd_font_advance(f, glyphs[i]);
        offsets[i].advanceOffset = 0.0f;
        offsets[i].ascenderOffset = 0.0f;
    }
    if (count == 0)
        return;

    ginfos = (struct shaping_glyph_info *)calloc(count, sizeof(*ginfos));
    if (!ginfos)
        return;

    ctx.cache = cache;
    ctx.script = script_id > Script_LastId ? Script_Unknown : script_id;
    ctx.text = text;
    ctx.length = text_len;
    ctx.is_rtl = rtl ? TRUE : FALSE;
    ctx.is_sideways = FALSE;
    ctx.u.pos.glyphs = glyphs;
    ctx.u.pos.glyph_props = props;
    ctx.u.pos.text_props = tprops;
    ctx.u.pos.clustermap = clustermap;
    ctx.glyph_count = count;
    ctx.emsize = (float)upem;
    ctx.measuring_mode = DWRITE_MEASURING_MODE_NATURAL;
    ctx.advances = advances;
    ctx.offsets = offsets;
    ctx.language_tag = 0;
    ctx.glyph_infos = ginfos;
    ctx.table = &cache->gpos;

    scripts[0] = script_tag ? script_tag : 0;
    scripts[1] = script_tag2;
    scripts[2] = 0;
    shape_get_positions(&ctx, scripts);

    free(ginfos);
}

/* --- per-lookup trace capture (single-threaded, like pydwshape's hook) --- */

#define WD_TRACE_MAX_STAGES 2048
#define WD_TRACE_MAX_GLYPHS 1024

typedef struct wd_trace_stage
{
    unsigned table;
    unsigned seq;
    unsigned count;
    uint16_t glyphs[WD_TRACE_MAX_GLYPHS];
} wd_trace_stage;

static wd_trace_stage g_trace[WD_TRACE_MAX_STAGES];
static unsigned g_trace_count = 0;

void wd_port_trace(unsigned int table_kind, unsigned int seq, const UINT16 *glyphs, unsigned int glyph_count)
{
    wd_trace_stage *s;
    unsigned int i, n;
    if (g_trace_count >= WD_TRACE_MAX_STAGES)
        return;
    if (!glyphs)
        return;
    s = &g_trace[g_trace_count];
    s->table = table_kind;
    s->seq = seq;
    n = glyph_count > WD_TRACE_MAX_GLYPHS ? WD_TRACE_MAX_GLYPHS : glyph_count;
    s->count = n;
    for (i = 0; i < n; ++i)
        s->glyphs[i] = glyphs[i];
    g_trace_count++;
}

void wd_trace_reset(void)
{
    g_trace_count = 0;
}

unsigned wd_trace_count(void)
{
    return g_trace_count;
}

int wd_trace_get(unsigned i, wd_stage_view *v)
{
    if (i >= g_trace_count || !v)
        return -1;
    v->table = g_trace[i].table;
    v->seq = g_trace[i].seq;
    v->count = g_trace[i].count;
    v->glyphs = g_trace[i].glyphs;
    return 0;
}

/* --- public API ----------------------------------------------------------- */

int wd_shape(const wd_shape_opts *o, wd_glyph *out, unsigned max_out, unsigned *n)
{
    struct wd_font *f;
    struct scriptshaping_cache *cache;
    uint16_t *glyphs = NULL;
    DWRITE_SHAPING_GLYPH_PROPERTIES *props = NULL;
    struct shaping_glyph_info *ginfos = NULL;
    DWRITE_SHAPING_TEXT_PROPERTIES *tprops = NULL;
    uint16_t *clustermap = NULL;
    float *adv = NULL;
    DWRITE_GLYPH_OFFSET *offs = NULL;
    unsigned count = 0, cap;
    unsigned upem;
    HRESULT hr;
    unsigned i;
    unsigned cur_cluster = 0;

    if (!o || !o->font || !o->text || !out || !n || o->text_len == 0)
        return -1;
    *n = 0;
    wd_trace_reset();

    f = wd_font_open(o->font, o->font_size);
    if (!f)
        return -1;
    cache = create_scriptshaping_cache(f, &wd_font_ops);
    if (!cache)
    {
        wd_font_close(f);
        return -1;
    }

    upem = wd_font_upem(f);
    cap = o->text_len * 2 + 16;

    hr = run_gsub(f, cache, o->text, o->text_len, o->script_id, o->script_tag, o->script_tag2,
            o->rtl, cap, &glyphs, &props, &ginfos, &count, &tprops, &clustermap);
    if (FAILED(hr) && hr != E_NOT_SUFFICIENT_BUFFER)
    {
        release_scriptshaping_cache(cache);
        wd_font_close(f);
        return -1;
    }

    if (o->want_positions && count)
    {
        adv = (float *)calloc(count, sizeof(*adv));
        offs = (DWRITE_GLYPH_OFFSET *)calloc(count, sizeof(*offs));
        if (adv && offs)
            run_gpos(f, cache, o->text, o->text_len, o->script_id, o->script_tag, o->script_tag2,
                    o->rtl, count, glyphs, props, tprops, clustermap, upem, adv, offs);
    }

    if (count > max_out)
    {
        free(glyphs);
        free(props);
        free(ginfos);
        free(tprops);
        free(clustermap);
        free(adv);
        free(offs);
        release_scriptshaping_cache(cache);
        wd_font_close(f);
        return -2;
    }

    for (i = 0; i < count; ++i)
    {
        if (props[i].isClusterStart)
            cur_cluster = (i < count && ginfos) ? ginfos[i].start_text_idx : 0;
        out[i].gid = glyphs[i];
        out[i].cluster = cur_cluster;
        out[i].ax = adv ? adv[i] : 0.0f;
        out[i].ay = 0.0f;
        out[i].dx = (adv && offs) ? offs[i].advanceOffset : 0.0f;
        out[i].dy = (adv && offs) ? offs[i].ascenderOffset : 0.0f;
    }
    *n = count;

    free(glyphs);
    free(props);
    free(ginfos);
    free(tprops);
    free(clustermap);
    free(adv);
    free(offs);
    release_scriptshaping_cache(cache);
    wd_font_close(f);
    return 0;
}
