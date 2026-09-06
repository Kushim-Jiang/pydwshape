/* wd_script.c — Unicode script auto-detection (see wd_script.h).
 *
 * Detection data below is a compact subset of Unicode Scripts.txt for the
 * scripts most relevant to font shaping; Common/Inherited/Unknown are neutral.
 * The winner is the script with the most letter codepoints.
 *
 * OpenType tag mapping mirrors Wine's analyzer `dwritescripts_properties`
 * scripttags (secondary = legacy tag for Indic scripts, e.g. dev2/dev2...). */

#include "wd_script.h"
#include "scripts.h"

#include <string.h>

/* (lo, hi, unicode_script_id) — inclusive ranges. */
static const struct range
{
    uint32_t lo;
    uint32_t hi;
    unsigned sid;
} SCRIPT_RANGES[] =
{
    /* Latin */
    { 0x0041, 0x005a, Script_Latin }, { 0x0061, 0x007a, Script_Latin },
    { 0x00aa, 0x00aa, Script_Latin }, { 0x00ba, 0x00ba, Script_Latin },
    { 0x00c0, 0x00d6, Script_Latin }, { 0x00d8, 0x00f6, Script_Latin },
    { 0x00f8, 0x02b8, Script_Latin }, { 0x1e00, 0x1eff, Script_Latin },
    { 0x2c60, 0x2c7f, Script_Latin }, { 0xa720, 0xa7ff, Script_Latin },
    /* Greek */
    { 0x0370, 0x0373, Script_Greek }, { 0x0376, 0x0377, Script_Greek },
    { 0x037b, 0x037d, Script_Greek }, { 0x0386, 0x0386, Script_Greek },
    { 0x0388, 0x03ff, Script_Greek }, { 0x1f00, 0x1fff, Script_Greek },
    /* Cyrillic */
    { 0x0400, 0x0484, Script_Cyrillic }, { 0x0487, 0x052f, Script_Cyrillic },
    { 0x2de0, 0x2dff, Script_Cyrillic }, { 0xa640, 0xa69f, Script_Cyrillic },
    /* Armenian */
    { 0x0531, 0x058f, Script_Armenian },
    /* Hebrew */
    { 0x0591, 0x05f4, Script_Hebrew },
    /* Arabic (incl. presentation forms A/B) */
    { 0x0600, 0x06ff, Script_Arabic }, { 0x0750, 0x077f, Script_Arabic },
    { 0x08a0, 0x08ff, Script_Arabic }, { 0xfb50, 0xfdff, Script_Arabic },
    { 0xfe70, 0xfeff, Script_Arabic },
    /* Syriac */
    { 0x0700, 0x074f, Script_Syriac },
    /* Thaana */
    { 0x0780, 0x07bf, Script_Thaana },
    /* N'Ko */
    { 0x07c0, 0x07ff, Script_Nko },
    /* Devanagari */
    { 0x0900, 0x097f, Script_Devanagari }, { 0xa8e0, 0xa8ff, Script_Devanagari },
    /* Bengali */
    { 0x0980, 0x09ff, Script_Bengali },
    /* Gurmukhi */
    { 0x0a00, 0x0a7f, Script_Gurmukhi },
    /* Gujarati */
    { 0x0a80, 0x0aff, Script_Gujarati },
    /* Oriya */
    { 0x0b00, 0x0b7f, Script_Oriya },
    /* Tamil */
    { 0x0b80, 0x0bff, Script_Tamil },
    /* Telugu */
    { 0x0c00, 0x0c7f, Script_Telugu },
    /* Kannada */
    { 0x0c80, 0x0cff, Script_Kannada },
    /* Malayalam */
    { 0x0d00, 0x0d7f, Script_Malayalam },
    /* Sinhala */
    { 0x0d80, 0x0dff, Script_Sinhala },
    /* Thai */
    { 0x0e00, 0x0e7f, Script_Thai },
    /* Lao */
    { 0x0e80, 0x0eff, Script_Lao },
    /* Tibetan */
    { 0x0f00, 0x0fff, Script_Tibetan },
    /* Myanmar */
    { 0x1000, 0x109f, Script_Myanmar }, { 0xa9e0, 0xa9ff, Script_Myanmar },
    /* Georgian */
    { 0x10a0, 0x10ff, Script_Georgian }, { 0x1c90, 0x1cbf, Script_Georgian },
    /* Hangul */
    { 0x1100, 0x11ff, Script_Hangul }, { 0x3130, 0x318f, Script_Hangul },
    { 0xac00, 0xd7af, Script_Hangul },
    /* Ethiopic */
    { 0x1200, 0x137f, Script_Ethiopic }, { 0x1380, 0x139f, Script_Ethiopic },
    { 0x2d80, 0x2ddf, Script_Ethiopic }, { 0xab00, 0xab2f, Script_Ethiopic },
    /* Cherokee */
    { 0x13a0, 0x13ff, Script_Cherokee }, { 0xab70, 0xabbf, Script_Cherokee },
    /* Canadian Aboriginal */
    { 0x1400, 0x167f, Script_Canadian_Aboriginal }, { 0x18b0, 0x18ff, Script_Canadian_Aboriginal },
    /* Ogham */
    { 0x1680, 0x169f, Script_Ogham },
    /* Runic */
    { 0x16a0, 0x16ff, Script_Runic },
    /* Khmer */
    { 0x1780, 0x17ff, Script_Khmer }, { 0x19e0, 0x19ff, Script_Khmer },
    /* Mongolian */
    { 0x1800, 0x18af, Script_Mongolian },
    /* Hiragana */
    { 0x3040, 0x309f, Script_Hiragana },
    /* Katakana */
    { 0x30a0, 0x30ff, Script_Katakana }, { 0x31f0, 0x31ff, Script_Katakana },
    { 0xff66, 0xff9d, Script_Katakana },
    /* Bopomofo */
    { 0x3100, 0x312f, Script_Bopomofo }, { 0x31a0, 0x31bf, Script_Bopomofo },
    /* CJK (Han) */
    { 0x3400, 0x4dbf, Script_Han }, { 0x4e00, 0x9fff, Script_Han },
    { 0xf900, 0xfaff, Script_Han },
    /* Yi */
    { 0xa000, 0xa48f, Script_Yi }, { 0xa490, 0xa4cf, Script_Yi },
    /* Vai */
    { 0xa500, 0xa63f, Script_Vai },
    /* Bamum */
    { 0xa6a0, 0xa6ff, Script_Bamum },
    /* Kayah Li */
    { 0xa900, 0xa92f, Script_Kayah_Li },
    /* Rejang */
    { 0xa930, 0xa95f, Script_Rejang },
    /* Javanese */
    { 0xa980, 0xa9df, Script_Javanese },
    /* Cham */
    { 0xaa00, 0xaa5f, Script_Cham },
    /* Tai Viet */
    { 0xaa80, 0xaadf, Script_Tai_Viet },
    /* Meetei Mayek */
    { 0xabc0, 0xabff, Script_Meetei_Mayek },
    /* Syloti Nagri */
    { 0xa800, 0xa82f, Script_Syloti_Nagri },
    /* Tai Tham */
    { 0x1a20, 0x1aaf, Script_Tai_Tham },
    /* New Tai Lue */
    { 0x1980, 0x19df, Script_New_Tai_Lue },
    /* Buginese */
    { 0x1a00, 0x1a1f, Script_Buginese },
    /* Balinese */
    { 0x1b00, 0x1b7f, Script_Balinese },
    /* Sundanese */
    { 0x1b80, 0x1bbf, Script_Sundanese },
    /* Lepcha */
    { 0x1c00, 0x1c4f, Script_Lepcha },
    /* Ol Chiki */
    { 0x1c50, 0x1c7f, Script_Ol_Chiki },
    /* Lisu */
    { 0xa4d0, 0xa4ff, Script_Lisu },
    /* Saurashtra */
    { 0xa880, 0xa8df, Script_Saurashtra },
    /* Mandaic */
    { 0x0840, 0x085f, Script_Mandaic },
};

static unsigned script_of(uint32_t cp)
{
    size_t i;
    for (i = 0; i < sizeof(SCRIPT_RANGES) / sizeof(SCRIPT_RANGES[0]); ++i)
        if (cp >= SCRIPT_RANGES[i].lo && cp <= SCRIPT_RANGES[i].hi)
            return SCRIPT_RANGES[i].sid;
    return Script_Unknown;
}

unsigned wd_detect_script(const uint16_t *text, unsigned len)
{
    unsigned counts[Script_LastId + 1];
    unsigned i = 0;
    unsigned best = Script_Latin; /* neutral default when nothing significant */
    unsigned best_count = 0;

    memset(counts, 0, sizeof(counts));
    while (i < len)
    {
        uint32_t cp = text[i++];
        unsigned sid;
        if (cp >= 0xd800 && cp <= 0xdbff && i < len && text[i] >= 0xdc00 && text[i] <= 0xdfff)
            cp = 0x10000 + ((cp - 0xd800) << 10) + (text[i++] - 0xdc00);
        sid = script_of(cp);
        if (sid > 0 && sid <= Script_LastId && sid != Script_Common && sid != Script_Inherited)
            counts[sid]++;
    }

    for (i = 1; i <= Script_LastId; ++i)
    {
        if (counts[i] > best_count)
        {
            best_count = counts[i];
            best = i;
        }
    }
    return best_count ? best : Script_Latin;
}

/* OpenType script tags per unicode_script_id (primary[, secondary]); values
 * are DWrite little-endian numeric 4CC ('mong' == 0x676E6F6D). */
#define T4(a, b, c, d) ((uint32_t)(a) | ((uint32_t)(b) << 8) | \
                        ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))

static const struct sid_tags
{
    unsigned sid;
    uint32_t t[2];
} SCRIPT_TAGS[] =
{
    { Script_Arabic, { T4('a','r','a','b'), 0 } },
    { Script_Syriac, { T4('s','y','r','c'), 0 } },
    { Script_Mongolian, { T4('m','o','n','g'), 0 } },
    { Script_Nko, { T4('n','k','o',' '), 0 } },
    { Script_Latin, { T4('l','a','t','n'), 0 } },
    { Script_Greek, { T4('g','r','e','k'), 0 } },
    { Script_Cyrillic, { T4('c','y','r','l'), 0 } },
    { Script_Armenian, { T4('a','r','m','n'), 0 } },
    { Script_Hebrew, { T4('h','e','b','r'), 0 } },
    { Script_Thaana, { T4('t','h','a','a'), 0 } },
    { Script_Devanagari, { T4('d','e','v','2'), T4('d','e','v','a') } },
    { Script_Bengali, { T4('b','n','g','2'), T4('b','e','n','g') } },
    { Script_Gurmukhi, { T4('g','u','r','2'), T4('g','u','r','u') } },
    { Script_Gujarati, { T4('g','j','r','2'), T4('g','u','j','r') } },
    { Script_Oriya, { T4('o','r','y','2'), T4('o','r','y','a') } },
    { Script_Tamil, { T4('t','m','l','2'), T4('t','a','m','l') } },
    { Script_Telugu, { T4('t','e','l','2'), T4('t','e','l','u') } },
    { Script_Kannada, { T4('k','n','d','2'), T4('k','n','d','a') } },
    { Script_Malayalam, { T4('m','l','m','2'), T4('m','l','y','m') } },
    { Script_Sinhala, { T4('s','i','n','h'), 0 } },
    { Script_Thai, { T4('t','h','a','i'), 0 } },
    { Script_Lao, { T4('l','a','o',' '), 0 } },
    { Script_Tibetan, { T4('t','i','b','t'), 0 } },
    { Script_Myanmar, { T4('m','y','m','2'), T4('m','y','m','r') } },
    { Script_Georgian, { T4('g','e','o','r'), 0 } },
    { Script_Hangul, { T4('h','a','n','g'), 0 } },
    { Script_Ethiopic, { T4('e','t','h','i'), 0 } },
    { Script_Cherokee, { T4('c','h','e','r'), 0 } },
    { Script_Canadian_Aboriginal, { T4('c','a','n','s'), 0 } },
    { Script_Ogham, { T4('o','g','a','m'), 0 } },
    { Script_Runic, { T4('r','u','n','r'), 0 } },
    { Script_Khmer, { T4('k','h','m','r'), 0 } },
    { Script_Hiragana, { T4('k','a','n','a'), 0 } },
    { Script_Katakana, { T4('k','a','n','a'), 0 } },
    { Script_Han, { T4('h','a','n','i'), 0 } },
    { Script_Bopomofo, { T4('b','o','p','o'), 0 } },
    { Script_Yi, { T4('y','i',' ',' '), 0 } },
    { Script_Vai, { T4('v','a','i',' '), 0 } },
    { Script_Bamum, { T4('b','a','m','u'), 0 } },
    { Script_Kayah_Li, { T4('k','a','l','i'), 0 } },
    { Script_Rejang, { T4('r','j','n','g'), 0 } },
    { Script_Javanese, { T4('j','a','v','a'), 0 } },
    { Script_Cham, { T4('c','h','a','m'), 0 } },
    { Script_Tai_Viet, { T4('t','a','v','t'), 0 } },
    { Script_Meetei_Mayek, { T4('m','t','e','i'), 0 } },
    { Script_Syloti_Nagri, { T4('s','y','l','o'), 0 } },
    { Script_Tai_Tham, { T4('l','a','n','a'), 0 } },
    { Script_New_Tai_Lue, { T4('t','a','l','u'), 0 } },
    { Script_Buginese, { T4('b','u','g','i'), 0 } },
    { Script_Balinese, { T4('b','a','l','i'), 0 } },
    { Script_Sundanese, { T4('s','u','n','d'), 0 } },
    { Script_Lepcha, { T4('l','e','p','c'), 0 } },
    { Script_Ol_Chiki, { T4('o','l','c','k'), 0 } },
    { Script_Lisu, { T4('l','i','s','u'), 0 } },
    { Script_Saurashtra, { T4('s','a','u','r'), 0 } },
    { Script_Mandaic, { T4('m','a','n','d'), 0 } },
};

void wd_script_tags(unsigned script_id, uint32_t tags[3])
{
    size_t i;
    tags[0] = tags[1] = tags[2] = 0;
    for (i = 0; i < sizeof(SCRIPT_TAGS) / sizeof(SCRIPT_TAGS[0]); ++i)
    {
        if (SCRIPT_TAGS[i].sid == script_id)
        {
            tags[0] = SCRIPT_TAGS[i].t[0];
            tags[1] = SCRIPT_TAGS[i].t[1];
            return;
        }
    }
}
