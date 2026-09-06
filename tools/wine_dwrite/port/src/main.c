/* main.c — CLI driver for the standalone Wine DWrite shaping port.
 *   wdmain --font <file> (--text <utf8> | --text-file <file>)
 *          [--script <tag4>] [--rtl] [--pos]
 * Prints babelsoft-style final glyph JSON to stdout.
 *
 * Text is accepted as UTF-8 (from an arg or a file) and decoded to UTF-16 so
 * non-ASCII Mongolian etc. works regardless of the host ANSI codepage.
 * Without --script the script is auto-detected from the text (like DWriteCore). */

#include "dwrite_private.h"
#include "scripts.h"
#include "wd_engine.h"
#include "wd_script.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void tag4str(uint32_t tag, char out[5])
{
    out[0] = (char)(tag & 0xff);
    out[1] = (char)((tag >> 8) & 0xff);
    out[2] = (char)((tag >> 16) & 0xff);
    out[3] = (char)((tag >> 24) & 0xff);
    out[4] = 0;
}
static long read_file(const char *path, unsigned char **out)
{
    FILE *fp = fopen(path, "rb");
    long sz;
    unsigned char *buf;
    if (!fp)
        return -1;
    fseek(fp, 0, SEEK_END);
    sz = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    buf = (unsigned char *)malloc(sz > 0 ? (size_t)sz : 1);
    if (!buf)
    {
        fclose(fp);
        return -1;
    }
    if (sz > 0 && fread(buf, 1, (size_t)sz, fp) != (size_t)sz)
    {
        free(buf);
        fclose(fp);
        return -1;
    }
    fclose(fp);
    *out = buf;
    return sz;
}

/* UTF-8 -> UTF-16. Returns number of code units written (0 on error). */
static unsigned utf8_to_utf16(const unsigned char *s, long len, uint16_t *out, unsigned cap)
{
    long i = 0;
    unsigned n = 0;
    while (i < len)
    {
        unsigned c;
        unsigned char b = s[i];
        if (b < 0x80)
        {
            c = b;
            i += 1;
        }
        else if ((b >> 5) == 0x6)
        {
            if (i + 1 >= len)
                return 0;
            c = ((b & 0x1f) << 6) | (s[i + 1] & 0x3f);
            i += 2;
        }
        else if ((b >> 4) == 0xe)
        {
            if (i + 2 >= len)
                return 0;
            c = ((b & 0x0f) << 12) | ((s[i + 1] & 0x3f) << 6) | (s[i + 2] & 0x3f);
            i += 3;
        }
        else if ((b >> 3) == 0x1e)
        {
            if (i + 3 >= len)
                return 0;
            c = ((b & 0x07) << 18) | ((s[i + 1] & 0x3f) << 12) |
                ((s[i + 2] & 0x3f) << 6) | (s[i + 3] & 0x3f);
            i += 4;
        }
        else
            return 0;

        if (c > 0xffff)
        {
            if (n + 2 > cap)
                return 0;
            c -= 0x10000;
            out[n++] = (uint16_t)(0xd800 + (c >> 10));
            out[n++] = (uint16_t)(0xdc00 + (c & 0x3ff));
        }
        else
        {
            if (n + 1 > cap)
                return 0;
            out[n++] = (uint16_t)c;
        }
    }
    return n;
}

struct tagmap
{
    const char *name;   /* iso15924 / opentype tag */
    unsigned script_id; /* scripts.h unicode_script_id */
};

static unsigned tag_to_script_id(const char *name)
{
    static const struct tagmap map[] = {
        { "arab", Script_Arabic },      { "syrc", Script_Syriac },
        { "mong", Script_Mongolian },   { "latn", Script_Latin },
        { "hebr", Script_Hebrew },      { "deva", Script_Devanagari },
        { "cyrl", Script_Cyrillic },    { "grek", Script_Greek },
        { "hang", Script_Hangul },      { "kana", Script_Katakana },
        { "hani", Script_Han },         { "thai", Script_Thai },
        { "beng", Script_Bengali },     { "guru", Script_Gurmukhi },
        { "gujr", Script_Gujarati },    { "knda", Script_Kannada },
        { "mlym", Script_Malayalam },   { "orya", Script_Oriya },
        { "taml", Script_Tamil },       { "telu", Script_Telugu },
        { "sinh", Script_Sinhala },     { "myan", Script_Myanmar },
        { "khme", Script_Khmer },       { "lao", Script_Lao },
        { "tibt", Script_Tibetan },     { "ethi", Script_Ethiopic },
    };
    size_t i;
    if (!name)
        return Script_Common;
    for (i = 0; i < sizeof(map) / sizeof(map[0]); ++i)
        if (strncmp(map[i].name, name, 4) == 0)
            return map[i].script_id;
    return Script_Unknown;
}

static uint32_t fourcc(const char *s)
{
    unsigned char c[4] = { ' ', ' ', ' ', ' ' };
    size_t l = s ? strlen(s) : 0;
    size_t i;
    for (i = 0; i < l && i < 4; ++i)
        c[i] = (unsigned char)s[i];
    /* DWrite little-endian numeric 4CC */
    return (uint32_t)c[0] | ((uint32_t)c[1] << 8) | ((uint32_t)c[2] << 16) | ((uint32_t)c[3] << 24);
}

static const char *arg_value(int argc, char **argv, int *i)
{
    if (*i + 1 < argc)
        return argv[++*i];
    return NULL;
}

/* print the per-lookup trace as JSON (seq 0 = nominal cmap baseline) */
static void print_stages(void)
{
    enum { MAXG = 4096 };
    unsigned t, u;
    unsigned pv_table = 0, pv_seq = 0, pv_n = 0;
    uint16_t pv_g[MAXG];
    int first = 1;

    printf(",\"stages\":[");
    for (t = 0; t < wd_trace_count(); ++t)
    {
        wd_stage_view v;
        unsigned changed = 0;
        char name[32];
        if (wd_trace_get(t, &v) != 0)
            continue;

        if (v.table != pv_table || v.seq != pv_seq || v.count != pv_n)
            changed = 1;
        else
        {
            for (u = 0; u < v.count; ++u)
                if (v.glyphs[u] != pv_g[u]) { changed = 1; break; }
        }

        if (v.seq == 0)
            snprintf(name, sizeof(name), "%s nominal", v.table == 0 ? "GSUB" : "GPOS");
        else
            snprintf(name, sizeof(name), "%s lookup %u", v.table == 0 ? "GSUB" : "GPOS", v.seq);

        printf("%s{\"m\":\"%s\",\"eff\":%s,\"g\":[",
                first ? "" : ",", name, (changed || v.seq == 0) ? "true" : "false");
        first = 0;
        for (u = 0; u < v.count; ++u)
        {
            if (u)
                printf(",");
            printf("%u", v.glyphs[u]);
        }
        printf("]}");

        pv_table = v.table;
        pv_seq = v.seq;
        pv_n = v.count;
        for (u = 0; u < v.count; ++u)
            pv_g[u] = v.glyphs[u];
    }
    printf("]");
}

int main(int argc, char **argv)
{
    const char *font_path = NULL, *text_str = NULL, *text_file = NULL, *script = NULL;
    unsigned char *font_data = NULL, *text_bytes = NULL;
    long font_size, text_size = 0;
    uint16_t *text16 = NULL;
    wd_glyph *out = NULL;
    unsigned n = 0, cap;
    unsigned script_id = Script_Common;
    uint32_t tag = 0, tag2 = 0;
    int rtl = 0, pos = 0, trace = 0;
    int i, rc;
    wd_shape_opts opts;
    char script_used[5] = { 0 };

    for (i = 1; i < argc; ++i)
    {
        if (!strcmp(argv[i], "--font")) font_path = arg_value(argc, argv, &i);
        else if (!strcmp(argv[i], "--text")) text_str = arg_value(argc, argv, &i);
        else if (!strcmp(argv[i], "--text-file")) text_file = arg_value(argc, argv, &i);
        else if (!strcmp(argv[i], "--script")) script = arg_value(argc, argv, &i);
        else if (!strcmp(argv[i], "--rtl")) rtl = 1;
        else if (!strcmp(argv[i], "--pos")) pos = 1;
        else if (!strcmp(argv[i], "--trace")) trace = 1;
        else
        {
            fprintf(stderr, "unknown arg: %s\n", argv[i]);
            return 2;
        }
    }

    if (!font_path || (!text_str && !text_file))
    {
        fprintf(stderr, "usage: wdmain --font <file> (--text <utf8>|--text-file <file>) [--script <tag4>] [--rtl] [--pos]\n");
        return 2;
    }

    font_size = read_file(font_path, &font_data);
    if (font_size <= 0)
    {
        fprintf(stderr, "cannot read font: %s\n", font_path);
        return 2;
    }

    if (text_str)
    {
        text_bytes = (unsigned char *)text_str;
        text_size = (long)strlen(text_str);
    }
    else
    {
        text_size = read_file(text_file, &text_bytes);
        if (text_size < 0)
        {
            fprintf(stderr, "cannot read text file: %s\n", text_file);
            return 2;
        }
    }

    text16 = (uint16_t *)calloc((size_t)text_size + 1, sizeof(*text16));
    if (!text16)
        return 2;

    {
        unsigned tlen = utf8_to_utf16(text_bytes, text_size, text16, (unsigned)text_size + 1);
        if (tlen == 0 && text_size > 0)
        {
            fprintf(stderr, "text is not valid UTF-8\n");
            return 2;
        }
        text_size = (long)tlen;
    }

    if (script)
    {
        uint32_t tags[3] = { 0, 0, 0 };
        script_id = tag_to_script_id(script);
        wd_script_tags(script_id, tags);
        tag = tags[0] ? tags[0] : fourcc(script);
        tag2 = tags[1];
    }
    else
    {
        /* auto-detect like DWriteCore: dominant Unicode script of the text */
        script_id = wd_detect_script(text16, (unsigned)text_size);
        {
            uint32_t tags[3] = { 0, 0, 0 };
            wd_script_tags(script_id, tags);
            tag = tags[0];
            tag2 = tags[1];
        }
    }
    tag4str(tag, script_used);

    cap = (unsigned)text_size * 8 + 64;
    out = (wd_glyph *)calloc(cap, sizeof(*out));
    if (!out)
        return 2;

    memset(&opts, 0, sizeof(opts));
    opts.font = font_data;
    opts.font_size = (size_t)font_size;
    opts.text = text16;
    opts.text_len = (unsigned)text_size;
    opts.script_id = script_id;
    opts.script_tag = tag;
    opts.script_tag2 = tag2;
    opts.rtl = rtl;
    opts.want_positions = pos;

    rc = wd_shape(&opts, out, cap, &n);
    if (rc == 0)
    {
        unsigned k;
        printf("{\"engine\":\"winedwrite\",\"script\":\"%s\",\"n\":%u,\"final\":[",
                script_used, n);
        for (k = 0; k < n; ++k)
        {
            if (k)
                printf(",");
            printf("{\"g\":%u,\"cl\":%u,\"ax\":%.1f,\"ay\":%.1f,\"dx\":%.1f,\"dy\":%.1f}",
                    out[k].gid, out[k].cluster, out[k].ax, out[k].ay, out[k].dx, out[k].dy);
        }
        printf("]");
        if (trace)
            print_stages();
        printf("}\n");
    }
    else if (rc == -2)
    {
        fprintf(stderr, "run exceeded buffer\n");
        rc = 3;
    }
    else
    {
        fprintf(stderr, "wd_shape failed (rc=%d)\n", rc);
        rc = 3;
    }

    free(out);
    free(text16);
    free(font_data);
    if (text_file)
        free(text_bytes);
    return rc;
}
