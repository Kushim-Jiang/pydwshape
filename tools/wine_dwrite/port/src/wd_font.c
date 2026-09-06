/* wd_font.c — raw-sfnt font driver (see wd_font.h). Cross-platform, no deps. */

#include "wd_font.h"

#include <stdlib.h>
#include <string.h>

static uint16_t rd_u16be(const uint8_t *p)
{
    return (uint16_t)((p[0] << 8) | p[1]);
}
static uint32_t rd_u32be(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

struct table_entry
{
    uint32_t tag;
    uint32_t offset;
    uint32_t length;
};

/* tag: DWrite little-endian numeric 4CC ("cmap" == 0x70616D63). Compared
 * byte-wise against the on-disk (big-endian) directory record tag. */
#define TAG4(a, b, c, d) \
    ((uint32_t)(a) | ((uint32_t)(b) << 8) | ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))

struct wd_font
{
    const uint8_t *data;
    size_t size;
    struct table_entry *tables;
    unsigned table_count;
    uint16_t upem;
    /* chosen cmap subtable */
    const uint8_t *cmap;
    uint32_t cmap_len;
    /* hmtx parse cache */
    const uint8_t *hmtx;
    uint32_t hmtx_len;
    unsigned num_hmetrics;
};

static const struct table_entry *find_table(const struct wd_font *f, uint32_t tag)
{
    unsigned i;
    for (i = 0; i < f->table_count; ++i)
        if (f->tables[i].tag == tag)
            return &f->tables[i];
    return NULL;
}

const uint8_t *wd_font_table(struct wd_font *f, uint32_t tag, uint32_t *size)
{
    const struct table_entry *e = find_table(f, tag);
    if (!e)
    {
        if (size) *size = 0;
        return NULL;
    }
    if (size) *size = e->length;
    return f->data + e->offset;
}

uint16_t wd_font_upem(struct wd_font *f)
{
    return f->upem;
}

/* pick a cmap subtable (BMP format 4 preferred, else format 12/13) */
static void pick_cmap(struct wd_font *f)
{
    uint32_t size;
    const uint8_t *cmap = wd_font_table(f, TAG4('c', 'm', 'a', 'p'), &size);
    unsigned num, i;
    const uint8_t *best4 = NULL, *best12 = NULL, *best0 = NULL;
    uint32_t len4 = 0, len12 = 0, len0 = 0;

    f->cmap = NULL;
    f->cmap_len = 0;
    if (!cmap || size < 4)
        return;
    num = rd_u16be(cmap + 2);
    for (i = 0; i < num; ++i)
    {
        const uint8_t *rec = cmap + 4 + i * 8;
        uint16_t plat = rd_u16be(rec);
        uint16_t enc = rd_u16be(rec + 2);
        uint32_t off = rd_u32be(rec + 4);
        const uint8_t *sub;
        uint16_t fmt;

        if (off + 2 > size)
            continue;
        sub = cmap + off;
        fmt = rd_u16be(sub);
        if (fmt == 4 && (plat == 3 || plat == 0) && !best4)
        {
            best4 = sub;
            len4 = size - off;
        }
        else if (fmt >= 12 && fmt <= 13 && (plat == 3 || plat == 0) && !best12)
        {
            best12 = sub;
            len12 = size - off;
        }
        else if (plat == 0 && !best0)
        {
            best0 = sub;
            len0 = size - off;
        }
    }
    if (best4)
    {
        f->cmap = best4;
        f->cmap_len = len4;
    }
    else if (best12)
    {
        f->cmap = best12;
        f->cmap_len = len12;
    }
    else
    {
        f->cmap = best0;
        f->cmap_len = len0;
    }
}

static uint16_t cmap4_lookup(const uint8_t *p, uint32_t cp)
{
    unsigned seg_count = rd_u16be(p + 6) / 2;
    const uint8_t *end_codes = p + 14;
    const uint8_t *start_codes = end_codes + seg_count * 2 + 2;
    const uint8_t *id_deltas = start_codes + seg_count * 2;
    const uint8_t *id_range_offsets = id_deltas + seg_count * 2;
    unsigned i;

    if (cp > 0xffff)
        return 0;
    for (i = 0; i < seg_count; ++i)
    {
        uint16_t end = rd_u16be(end_codes + i * 2);
        uint16_t start = rd_u16be(start_codes + i * 2);
        if (cp >= start && cp <= end)
        {
            uint16_t delta = rd_u16be(id_deltas + i * 2);
            uint16_t range_offset = rd_u16be(id_range_offsets + i * 2);
            if (range_offset == 0)
                return (uint16_t)((cp + delta) & 0xffff);
            else
            {
                /* glyphIdArray index: rangeOffset/2 + (cp-start) within idRangeOffset table */
                const uint8_t *gid_addr = id_range_offsets + i * 2 + range_offset + (cp - start) * 2;
                uint16_t gid = rd_u16be(gid_addr);
                return gid ? (uint16_t)((gid + delta) & 0xffff) : 0;
            }
        }
    }
    return 0;
}

static uint16_t cmap12_lookup(const uint8_t *p, uint32_t cp)
{
    uint32_t n_groups = rd_u32be(p + 12);
    uint32_t i;
    for (i = 0; i < n_groups; ++i)
    {
        const uint8_t *g = p + 16 + i * 12;
        uint32_t start = rd_u32be(g);
        uint32_t end = rd_u32be(g + 4);
        uint32_t start_gid = rd_u32be(g + 8);
        if (cp >= start && cp <= end)
            return (uint16_t)(start_gid + (cp - start));
    }
    return 0;
}

uint16_t wd_font_glyph(struct wd_font *f, uint32_t codepoint)
{
    if (!f->cmap || f->cmap_len < 2)
        return 0;
    switch (rd_u16be(f->cmap))
    {
        case 4:
            return cmap4_lookup(f->cmap, codepoint);
        case 12:
            return cmap12_lookup(f->cmap, codepoint);
        default:
            return 0;
    }
}

int wd_font_has_glyph(struct wd_font *f, uint32_t codepoint)
{
    return wd_font_glyph(f, codepoint) != 0;
}

static void parse_hmtx(struct wd_font *f)
{
    uint32_t sz;
    const uint8_t *hhea = wd_font_table(f, TAG4('h', 'h', 'e', 'a'), &sz);
    f->hmtx = NULL;
    f->num_hmetrics = 0;
    if (!hhea || sz < 36)
        return;
    f->num_hmetrics = rd_u16be(hhea + 34);
    f->hmtx = wd_font_table(f, TAG4('h', 'm', 't', 'x'), &f->hmtx_len);
    if (!f->hmtx)
        f->num_hmetrics = 0;
}

uint16_t wd_font_advance(struct wd_font *f, uint16_t gid)
{
    unsigned idx;
    if (!f->hmtx || f->num_hmetrics == 0)
        return 0;
    idx = gid < f->num_hmetrics ? gid : (f->num_hmetrics - 1);
    if ((uint32_t)(idx * 4 + 2) > f->hmtx_len)
        return 0;
    return rd_u16be(f->hmtx + idx * 4);
}

struct wd_font *wd_font_open(const uint8_t *data, size_t size)
{
    struct wd_font *f;
    uint32_t num;
    uint32_t i;
    const uint8_t *dir;
    const uint8_t *base; /* sfnt (or TTC face) base */
    uint32_t magic;

    if (!data || size < 12)
        return NULL;

    magic = rd_u32be(data);
    base = data;
    if (magic == 0x74746366) /* 'ttcf' — font collection; use face 0 */
    {
        uint32_t num_fonts, face_off;
        if (size < 16)
            return NULL;
        num_fonts = rd_u32be(data + 8);
        if (num_fonts < 1 || size < 12 + 4u)
            return NULL;
        face_off = rd_u32be(data + 12); /* face index 0 */
        if (face_off + 12 > size)
            return NULL;
        base = data + face_off;
    }

    f = (struct wd_font *)calloc(1, sizeof(*f));
    if (!f)
        return NULL;
    f->data = data;
    f->size = size;
    num = rd_u16be(base + 4);
    if (num > 4096)
    {
        free(f);
        return NULL;
    }
    f->tables = (struct table_entry *)calloc(num, sizeof(*f->tables));
    if (!f->tables)
    {
        free(f);
        return NULL;
    }
    f->table_count = num;
    dir = base + 12;
    if ((size_t)(dir - data) + (size_t)num * 16 > size)
    {
        free(f->tables);
        free(f);
        return NULL;
    }
    for (i = 0; i < num; ++i)
    {
        const uint8_t *rec = dir + i * 16;
        /* store the directory tag as a little-endian numeric so numeric
         * equality against DWrite 4CC constants works directly */
        f->tables[i].tag = (uint32_t)rec[0] | ((uint32_t)rec[1] << 8) |
                           ((uint32_t)rec[2] << 16) | ((uint32_t)rec[3] << 24);
        f->tables[i].offset = rd_u32be(rec + 8);
        f->tables[i].length = rd_u32be(rec + 12);
        if ((size_t)f->tables[i].offset + f->tables[i].length > size)
        {
            f->tables[i].length = 0; /* out-of-bounds table */
        }
    }

    {
        uint32_t sz;
        const uint8_t *head = wd_font_table(f, TAG4('h', 'e', 'a', 'd'), &sz);
        f->upem = (head && sz >= 18) ? rd_u16be(head + 18) : 1000;
    }
    pick_cmap(f);
    parse_hmtx(f);
    return f;
}

void wd_font_close(struct wd_font *f)
{
    if (!f)
        return;
    free(f->tables);
    free(f);
}
