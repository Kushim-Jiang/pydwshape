/* wd_json.c — JSON engine result builder (see wd_json.h). */

#include "wd_json.h"
#include "wd_engine.h"
#include "wd_script.h"
#include "scripts.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- tiny growable string builder ---------------------------------------- */

struct sb
{
    char *p;
    size_t len;
    size_t cap;
};

static int sb_reserve(struct sb *b, size_t extra)
{
    size_t need = b->len + extra + 1;
    char *np;
    if (need <= b->cap)
        return 0;
    {
        size_t ncap = b->cap ? b->cap * 2 : 256;
        while (ncap < need)
            ncap *= 2;
        np = (char *)realloc(b->p, ncap);
        if (!np)
            return -1;
        b->p = np;
        b->cap = ncap;
    }
    return 0;
}

static void sb_put(struct sb *b, const char *s)
{
    size_t l = strlen(s);
    if (sb_reserve(b, l) == 0)
    {
        memcpy(b->p + b->len, s, l);
        b->len += l;
        b->p[b->len] = 0;
    }
}

static void sb_putf(struct sb *b, const char *fmt, ...)
{
    va_list ap;
    int n;
    char tmp[256];

    va_start(ap, fmt);
    n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n < sizeof(tmp))
        sb_put(b, tmp);
    else
    {
        /* very long expansion: format twice */
        va_start(ap, fmt);
        sb_reserve(b, (size_t)n);
        vsnprintf(b->p + b->len, (size_t)n + 1, fmt, ap);
        va_end(ap);
        b->len += (size_t)n;
    }
}

static void sb_free(struct sb *b)
{
    free(b->p);
    b->p = NULL;
}

/* --- JSON assembly ------------------------------------------------------- */

static void tag4str(uint32_t tag, char out[5])
{
    out[0] = (char)(tag & 0xff);
    out[1] = (char)((tag >> 8) & 0xff);
    out[2] = (char)((tag >> 16) & 0xff);
    out[3] = (char)((tag >> 24) & 0xff);
    out[4] = 0;
}

static unsigned gids_equal(const uint16_t *a, unsigned na, const uint16_t *b, unsigned nb)
{
    unsigned i;
    if (na != nb)
        return 0;
    for (i = 0; i < na; ++i)
        if (a[i] != b[i])
            return 0;
    return 1;
}

char *wd_shape_json(const uint8_t *font, size_t font_size, const uint16_t *text,
        unsigned text_len, uint32_t tag1, uint32_t tag2,
        int rtl, int want_pos, int want_trace)
{
    struct sb b;
    wd_glyph *out = NULL;
    unsigned cap, n = 0, i;
    unsigned script_id = Script_Latin;
    char tagstr[5];
    wd_shape_opts opts;

    if (!font || !text || text_len == 0)
        return NULL;

    if (tag1)
    {
        /* resolve id from tags for reporting only */
    }
    else
    {
        uint32_t tags[3] = { 0, 0, 0 };
        script_id = wd_detect_script(text, text_len);
        wd_script_tags(script_id, tags);
        tag1 = tags[0];
        tag2 = tags[1];
    }
    tag4str(tag1, tagstr);

    cap = text_len * 8 + 64;
    out = (wd_glyph *)calloc(cap, sizeof(*out));
    if (!out)
        return NULL;

    memset(&opts, 0, sizeof(opts));
    opts.font = font;
    opts.font_size = font_size;
    opts.text = text;
    opts.text_len = text_len;
    opts.script_id = script_id;
    opts.script_tag = tag1;
    opts.script_tag2 = tag2;
    opts.rtl = rtl ? 1 : 0;
    opts.want_positions = want_pos ? 1 : 0;

    if (wd_shape(&opts, out, cap, &n) != 0)
    {
        free(out);
        return NULL;
    }

    memset(&b, 0, sizeof(b));
    sb_putf(&b, "{\"engine\":\"winedwrite\",\"script\":\"%s\",\"n\":%u,\"final\":[", tagstr, n);
    for (i = 0; i < n; ++i)
    {
        if (i)
            sb_put(&b, ",");
        sb_putf(&b, "{\"g\":%u,\"cl\":%u,\"ax\":%.2f,\"ay\":%.2f,\"dx\":%.2f,\"dy\":%.2f}",
                out[i].gid, out[i].cluster, out[i].ax, out[i].ay, out[i].dx, out[i].dy);
    }
    sb_put(&b, "]");

    if (want_trace)
    {
        enum { MAXG = 4096 };
        unsigned t, u;
        unsigned pv_table = 0, pv_seq = 0, pv_n = 0;
        uint16_t pv_g[MAXG];
        unsigned first = 1;

        sb_put(&b, ",\"stages\":[");
        for (t = 0; t < wd_trace_count(); ++t)
        {
            wd_stage_view v;
            unsigned changed = 0;
            char name[40];
            if (wd_trace_get(t, &v) != 0)
                continue;
            changed = !gids_equal(pv_g, pv_n, v.glyphs, v.count);
            if (v.seq == 0)
                snprintf(name, sizeof(name), "%s nominal", v.table == 0 ? "GSUB" : "GPOS");
            else
                snprintf(name, sizeof(name), "%s lookup %u", v.table == 0 ? "GSUB" : "GPOS", v.seq);

            sb_putf(&b, "%s{\"m\":\"%s\",\"eff\":%s,\"g\":[",
                    first ? "" : ",", name, (changed || v.seq == 0) ? "true" : "false");
            first = 0;
            for (u = 0; u < v.count; ++u)
            {
                if (u)
                    sb_put(&b, ",");
                sb_putf(&b, "%u", v.glyphs[u]);
            }
            sb_put(&b, "]}");

            pv_table = v.table;
            pv_seq = v.seq;
            pv_n = v.count;
            for (u = 0; u < v.count; ++u)
                pv_g[u] = v.glyphs[u];
        }
        sb_put(&b, "]");
    }
    sb_put(&b, "}");

    free(out);
    return b.p;
}

void wd_json_free(char *s)
{
    free(s);
}
