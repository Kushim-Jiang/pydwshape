/*
 * dwrite_private.h — PORT-PRIVATE umbrella header for the standalone Wine
 * DWrite shaping engine (tools/wine_dwrite/port).
 *
 * This is a SELF-CONTAINED replacement for Wine's dwrite_private.h +
 * SDK (dwrite_3.h/d2d1.h) + winternl.h + wine/debug.h, containing only what
 * the GSUB/GPOS shaping engine (opentype_shaping.c, shape_port.c) needs.
 *
 * It is deliberately free of COM, GDI, windows.h and Wine-internal headers so
 * the same sources compile on Windows (MinGW), Linux and macOS.
 *
 * The shaping structs/enums below are copied verbatim from upstream Wine
 * dlls/dwrite/dwrite_private.h and remain LGPL-2.1-or-later.
 */

#ifndef __WINE_DWRITE_PRIVATE_PORT_H
#define __WINE_DWRITE_PRIVATE_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/* Portable base types (Windows names, portable definitions)           */
/* ------------------------------------------------------------------ */

typedef int8_t   INT8;
typedef int16_t  INT16;
typedef int32_t  INT;
typedef int64_t  INT64;
typedef uint8_t  UINT8, BYTE;
typedef uint16_t UINT16, WORD, WCHAR, USHORT;
typedef uint32_t UINT, UINT32, DWORD;
typedef uint64_t UINT64, ULONGLONG;
typedef uint8_t  BOOLEAN;
typedef int      BOOL;
typedef uintptr_t ULONG_PTR;
typedef uintptr_t SIZE_T;
typedef uint32_t ULONG;
typedef char     CHAR;

/* PANOSE (winnt.h layout, 10 bytes) */
typedef struct _PANOSE
{
    BYTE bFamilyType;
    BYTE bSerifStyle;
    BYTE bWeight;
    BYTE bProportion;
    BYTE bContrast;
    BYTE bStrokeVariation;
    BYTE bArmStyle;
    BYTE bLetterForm;
    BYTE bMidline;
    BYTE bXHeight;
} PANOSE;

#ifndef TRUE
#define TRUE  1
#endif
#ifndef FALSE
#define FALSE 0
#endif
#ifndef NULL
#define NULL ((void *)0)
#endif

/* WCHAR here is always a 16-bit UTF-16 code unit (independent of wchar_t). */

typedef int32_t SHORT;
typedef int32_t HRESULT;
typedef uint32_t DWRITE_FONT_AXIS_TAG;

#ifndef S_OK
#define S_OK ((HRESULT)0)
#endif
#ifndef E_OUTOFMEMORY
#define E_OUTOFMEMORY ((HRESULT)0x8007000EL)
#endif
#ifndef E_NOT_SUFFICIENT_BUFFER
#define E_NOT_SUFFICIENT_BUFFER ((HRESULT)0x8007007AL)
#endif
#ifndef FAILED
#define FAILED(hr) ((HRESULT)(hr) < 0)
#endif

#ifndef min
#define min(a, b) (((a) < (b)) ? (a) : (b))
#endif
#ifndef max
#define max(a, b) (((a) > (b)) ? (a) : (b))
#endif

#ifndef ARRAY_SIZE
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#endif

#ifndef FIELD_OFFSET
#define FIELD_OFFSET(type, field) ((unsigned long)offsetof(type, field))
#endif

#ifndef __cdecl
#define __cdecl
#endif

/* ------------------------------------------------------------------ */
/* Byte order + small intrinsics (portable)                            */
/* ------------------------------------------------------------------ */

static inline uint16_t wd_bswap16(uint16_t x)
{
    return (uint16_t)((x >> 8) | (x << 8));
}
static inline uint32_t wd_bswap32(uint32_t x)
{
    return ((x >> 24) & 0xff) | ((x >> 8) & 0xff00) |
           ((x << 8) & 0xff0000) | ((x << 24) & 0xff000000);
}

#define RtlUshortByteSwap(x) wd_bswap16((uint16_t)(x))
#define RtlUlongByteSwap(x)  wd_bswap32((uint32_t)(x))

#ifndef __popcnt
#define __popcnt(x) __builtin_popcount((unsigned)(x))
#endif

/* MSVC BitScanForward/BitScanReverse (portable via GCC builtins) */
static inline BOOL BitScanForward(unsigned int *index, unsigned int mask)
{
    if (!mask)
        return FALSE;
    *index = (unsigned int)__builtin_ctz(mask);
    return TRUE;
}
static inline BOOL BitScanReverse(unsigned int *index, unsigned int mask)
{
    if (!mask)
        return FALSE;
    *index = 31u - (unsigned int)__builtin_clz(mask);
    return TRUE;
}

#ifndef IS_HIGH_SURROGATE
#define IS_HIGH_SURROGATE(wch) (((wch) >= 0xd800) && ((wch) <= 0xdbff))
#endif
#ifndef IS_LOW_SURROGATE
#define IS_LOW_SURROGATE(wch) (((wch) >= 0xdc00) && ((wch) <= 0xdfff))
#endif

/* Wine trie-table readers (upstream dwrite_private.h) */
static inline unsigned short get_table_entry_16(const unsigned short *table, WCHAR ch)
{
    return table[table[table[ch >> 8] + ((ch >> 4) & 0x0f)] + (ch & 0xf)];
}

static inline unsigned short get_table_entry_32(const unsigned short *table, UINT ch)
{
    return table[table[table[table[ch >> 12] + ((ch >> 8) & 0x0f)] + ((ch >> 4) & 0x0f)] + (ch & 0xf)];
}

extern const unsigned short wine_mirror_map[1428];

/* ------------------------------------------------------------------ */
/* Minimal DirectWrite data types used by the shaping engine           */
/* (layout-compatible subset of the DirectWrite SDK; no COM).          */
/* ------------------------------------------------------------------ */

typedef uint32_t DWRITE_FONT_FEATURE_TAG;

/* DWrite tags are stored as little-endian numerics: writing the value little-
 * endian yields the four ASCII bytes of the tag ("kern" == 0x6E72654B). The
 * engine reads on-table tags natively (table_read_dword), so this convention
 * keeps feature/script comparisons consistent. */
#define DWRITE_MAKE_OPENTYPE_TAG(a, b, c, d) \
    ((DWRITE_FONT_FEATURE_TAG)((uint32_t)(a) | ((uint32_t)(b) << 8) | \
                               ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24)))

#define MS_GSUB_TAG DWRITE_MAKE_OPENTYPE_TAG('G', 'S', 'U', 'B')
#define MS_GPOS_TAG DWRITE_MAKE_OPENTYPE_TAG('G', 'P', 'O', 'S')
/* MS_GDEF_TAG is defined in opentype_shaping.c (upstream opentype.c head). */

typedef struct DWRITE_GLYPH_OFFSET
{
    float ascenderOffset;
    float advanceOffset;
} DWRITE_GLYPH_OFFSET;

typedef struct DWRITE_FONT_FEATURE
{
    DWRITE_FONT_FEATURE_TAG nameTag;
    UINT32 parameter;
} DWRITE_FONT_FEATURE;

typedef struct DWRITE_TYPOGRAPHIC_FEATURES
{
    DWRITE_FONT_FEATURE *features;
    UINT32 featureCount;
} DWRITE_TYPOGRAPHIC_FEATURES;

typedef struct DWRITE_SHAPING_GLYPH_PROPERTIES
{
    UINT16 justification : 4;
    UINT16 isClusterStart : 1;
    UINT16 isDiacritic : 1;
    UINT16 isZeroWidthSpace : 1;
    UINT16 _reserved : 9;
} DWRITE_SHAPING_GLYPH_PROPERTIES;

typedef struct DWRITE_SHAPING_TEXT_PROPERTIES
{
    UINT16 isShapedToNextCluster : 1;
    UINT16 isShapedToCurrentCluster : 1;
    UINT16 canBreakShapingAfter : 1;
    UINT16 _reserved : 13;
} DWRITE_SHAPING_TEXT_PROPERTIES;

typedef enum DWRITE_MEASURING_MODE
{
    DWRITE_MEASURING_MODE_NATURAL,
    DWRITE_MEASURING_MODE_GDI_CLASSIC,
    DWRITE_MEASURING_MODE_GDI_NATURAL,
} DWRITE_MEASURING_MODE;

typedef enum DWRITE_INFORMATIONAL_STRING
{
    DWRITE_INFORMATIONAL_STRING_NONE,
    DWRITE_INFORMATIONAL_STRING_COPYRIGHT_NOTICE,
    DWRITE_INFORMATIONAL_STRING_VERSION_STRINGS,
    DWRITE_INFORMATIONAL_STRING_TRADEMARK,
    DWRITE_INFORMATIONAL_STRING_MANUFACTURER,
    DWRITE_INFORMATIONAL_STRING_DESIGNER,
    DWRITE_INFORMATIONAL_STRING_DESIGNER_URL,
    DWRITE_INFORMATIONAL_STRING_DESCRIPTION,
    DWRITE_INFORMATIONAL_STRING_FONT_VENDOR_URL,
    DWRITE_INFORMATIONAL_STRING_LICENSE_DESCRIPTION,
    DWRITE_INFORMATIONAL_STRING_LICENSE_INFO_URL,
    DWRITE_INFORMATIONAL_STRING_WIN32_FAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_WIN32_SUBFAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_TYPOGRAPHIC_FAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_TYPOGRAPHIC_SUBFAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_SAMPLE_TEXT,
    DWRITE_INFORMATIONAL_STRING_FULL_NAME,
    DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_NAME,
    DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_CID_NAME,
    DWRITE_INFORMATIONAL_STRING_WEIGHT_STRETCH_STYLE_FAMILY_NAME,
    DWRITE_INFORMATIONAL_STRING_DESIGN_SCRIPT_LANGUAGE_TAG,
    DWRITE_INFORMATIONAL_STRING_SUPPORTED_SCRIPT_LANGUAGE_TAG,
    DWRITE_INFORMATIONAL_STRING_PREFERRED_FAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_PREFERRED_SUBFAMILY_NAMES,
    DWRITE_INFORMATIONAL_STRING_SAMPLE_TEXT_STRING = 0x53747374,
    DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_CID_NAME_STRING = 0x44494320,
    DWRITE_INFORMATIONAL_STRING_WEIGHT_STRETCH_STYLE_FAMILY_NAME_STRING = 0x47545357,
    DWRITE_INFORMATIONAL_STRING_DESIGN_SCRIPT_LANGUAGE_TAG_STRING = 0x646c7473,
    DWRITE_INFORMATIONAL_STRING_SUPPORTED_SCRIPT_LANGUAGE_TAG_STRING = 0x73736c74,
} DWRITE_INFORMATIONAL_STRING;

/* ------------------------------------------------------------------ */
/* Raw font table handle used by the engine's table readers            */
/* (copied from upstream dwrite_private.h)                             */
/* ------------------------------------------------------------------ */

struct dwrite_fonttable
{
    const BYTE *data;
    void *context;
    UINT32 size;
    BOOL exists;
};

/* Parsed GSUB/GPOS top-level offsets (upstream dwrite_private.h) */
struct ot_gsubgpos_table
{
    struct dwrite_fonttable table;
    unsigned int script_list;
    unsigned int feature_list;
    unsigned int lookup_list;
};

/* ------------------------------------------------------------------ */
/* Shaping engine types (copied verbatim from upstream dwrite_private.h) */
/* ------------------------------------------------------------------ */

enum SCRIPT_JUSTIFY
{
    SCRIPT_JUSTIFY_NONE,
    SCRIPT_JUSTIFY_ARABIC_BLANK,
    SCRIPT_JUSTIFY_CHARACTER,
    SCRIPT_JUSTIFY_RESERVED1,
    SCRIPT_JUSTIFY_BLANK,
    SCRIPT_JUSTIFY_RESERVED2,
    SCRIPT_JUSTIFY_RESERVED3,
    SCRIPT_JUSTIFY_ARABIC_NORMAL,
    SCRIPT_JUSTIFY_ARABIC_KASHIDA,
    SCRIPT_JUSTIFY_ARABIC_ALEF,
    SCRIPT_JUSTIFY_ARABIC_HA,
    SCRIPT_JUSTIFY_ARABIC_RA,
    SCRIPT_JUSTIFY_ARABIC_BA,
    SCRIPT_JUSTIFY_ARABIC_BARA,
    SCRIPT_JUSTIFY_ARABIC_SEEN,
    SCRIPT_JUSTIFY_ARABIC_SEEN_M
};

struct scriptshaping_cache
{
    const struct shaping_font_ops *font;
    void *context;
    UINT16 upem;

    struct ot_gsubgpos_table gsub;
    struct ot_gsubgpos_table gpos;

    struct
    {
        struct dwrite_fonttable table;
        unsigned int classdef;
        unsigned int markattachclassdef;
        unsigned int markglyphsetdef;
    } gdef;
};

struct shaping_glyph_info
{
    /* Combined features mask. */
    unsigned int mask;
    /* Derived from glyph class, supplied by GDEF. */
    unsigned int props;
    /* Used for GPOS mark and cursive attachments. */
    int attach_chain;
    /* Only relevant for isClusterStart glyphs. Indicates text position for this cluster. */
    unsigned int start_text_idx;
    unsigned int codepoint;
};

struct shaping_glyph_properties
{
    UINT16 justification : 4;
    UINT16 isClusterStart : 1;
    UINT16 isDiacritic : 1;
    UINT16 isZeroWidthSpace : 1;
    UINT16 reserved : 1;
    UINT16 components : 4;
    UINT16 lig_component : 4;
};

struct scriptshaping_context;

typedef void (*p_apply_context_lookup)(struct scriptshaping_context *context, unsigned int lookup_index);

enum shaping_feature_flags
{
    FEATURE_GLOBAL = 0x1,
    FEATURE_GLOBAL_SEARCH = 0x2,
    FEATURE_MANUAL_ZWNJ = 0x4,
    FEATURE_MANUAL_ZWJ = 0x8,
    FEATURE_MANUAL_JOINERS = FEATURE_MANUAL_ZWNJ | FEATURE_MANUAL_ZWJ,
    FEATURE_HAS_FALLBACK = 0x10,
    FEATURE_NEEDS_FALLBACK = 0x20,
};

struct shaping_feature
{
    unsigned int tag;
    unsigned int index;
    unsigned int flags;
    unsigned int max_value;
    unsigned int default_value;
    unsigned int mask;
    unsigned int shift;
    unsigned int stage;
};

#define MAX_SHAPING_STAGE 16

struct shaping_features;

typedef void (*stage_func)(struct scriptshaping_context *context,
        const struct shaping_features *features);

struct shaping_stage
{
    stage_func func;
    unsigned int last_lookup;
};

struct shaping_features
{
    struct shaping_feature *features;
    size_t count;
    size_t capacity;
    unsigned int stage;
    struct shaping_stage stages[MAX_SHAPING_STAGE];
};

struct shaper
{
    void (*collect_features)(struct scriptshaping_context *context, struct shaping_features *features);
    void (*setup_masks)(struct scriptshaping_context *context, const struct shaping_features *features);
};

extern const struct shaper arabic_shaper;

extern void shape_enable_feature(struct shaping_features *features, unsigned int tag,
        unsigned int flags);
extern void shape_add_feature_full(struct shaping_features *features, unsigned int tag,
        unsigned int flags, unsigned int value);
extern unsigned int shape_get_feature_1_mask(const struct shaping_features *features,
        unsigned int tag);
extern void shape_start_next_stage(struct shaping_features *features, stage_func func);

struct scriptshaping_context
{
    struct scriptshaping_cache *cache;
    const struct shaper *shaper;
    unsigned int script;
    UINT32 language_tag;

    const WCHAR *text;
    unsigned int length;
    BOOL is_rtl;
    BOOL is_sideways;

    union
    {
        struct
        {
            const UINT16 *glyphs;
            const DWRITE_SHAPING_GLYPH_PROPERTIES *glyph_props;
            DWRITE_SHAPING_TEXT_PROPERTIES *text_props;
            const UINT16 *clustermap;
            p_apply_context_lookup apply_context_lookup;
        } pos;
        struct
        {
            UINT16 *glyphs;
            DWRITE_SHAPING_GLYPH_PROPERTIES *glyph_props;
            DWRITE_SHAPING_TEXT_PROPERTIES *text_props;
            UINT16 *clustermap;
            p_apply_context_lookup apply_context_lookup;
            unsigned int max_glyph_count;
            unsigned int capacity;
            const WCHAR *digits;
        } subst;
        struct
        {
            UINT16 *glyphs;
            struct shaping_glyph_properties *glyph_props;
            DWRITE_SHAPING_TEXT_PROPERTIES *text_props;
            UINT16 *clustermap;
            p_apply_context_lookup apply_context_lookup;
        } buffer;
    } u;

    const struct ot_gsubgpos_table *table; /* Either GSUB or GPOS. */
    struct
    {
        const DWRITE_TYPOGRAPHIC_FEATURES **features;
        const unsigned int *range_lengths;
        unsigned int range_count;
    } user_features;
    unsigned int global_mask;
    unsigned int lookup_mask; /* Currently processed feature mask, set in main loop. */
    unsigned int auto_zwj;
    unsigned int auto_zwnj;
    struct shaping_glyph_info *glyph_infos;
    unsigned int has_gpos_attachment : 1;

    unsigned int cur;
    unsigned int glyph_count;
    unsigned int nesting_level_left;

    float emsize;
    DWRITE_MEASURING_MODE measuring_mode;
    float *advances;
    DWRITE_GLYPH_OFFSET *offsets;
};

struct shaping_font_ops
{
    void (*grab_font_table)(void *context, UINT32 table, const BYTE **data, UINT32 *size, void **data_context);
    void (*release_font_table)(void *context, void *data_context);
    UINT16 (*get_font_upem)(void *context);
    BOOL (*has_glyph)(void *context, unsigned int codepoint);
    UINT16 (*get_glyph)(void *context, unsigned int codepoint);
};

extern struct scriptshaping_cache *create_scriptshaping_cache(void *context,
        const struct shaping_font_ops *font_ops);
extern void release_scriptshaping_cache(struct scriptshaping_cache *cache);

extern void opentype_layout_scriptshaping_cache_init(struct scriptshaping_cache *cache);
extern unsigned int opentype_layout_find_script(const struct scriptshaping_cache *cache, unsigned int kind,
        DWORD tag, unsigned int *script_index);
extern unsigned int opentype_layout_find_language(const struct scriptshaping_cache *cache, unsigned int kind,
        DWORD tag, unsigned int script_index, unsigned int *language_index);
extern void opentype_layout_apply_gsub_features(struct scriptshaping_context *context, unsigned int script_index,
        unsigned int language_index, struct shaping_features *features);
extern void opentype_layout_apply_gpos_features(struct scriptshaping_context *context, unsigned int script_index,
        unsigned int language_index, struct shaping_features *features);
extern void opentype_layout_unsafe_to_break(struct scriptshaping_context *context, unsigned int start,
        unsigned int end);

extern HRESULT shape_get_glyphs(struct scriptshaping_context *context, const unsigned int *scripts);
extern HRESULT shape_get_positions(struct scriptshaping_context *context, const unsigned int *scripts);

/* helpers used across the two translation units */
extern bool opentype_is_whitespace(unsigned int codepoint);
extern BOOL opentype_layout_check_feature(struct scriptshaping_context *context, unsigned int script_index,
        unsigned int language_index, struct shaping_feature *feature, unsigned int glyph_count,
        const UINT16 *glyphs, UINT8 *feature_applies);

/* PORT EXTENSION — per-lookup trace hook, called by the engine just before a
 * whole-run lookup application. table_kind: 0 = GSUB, 1 = GPOS. seq: 0 means
 * "nominal cmap baseline", otherwise 1-based lookup sequence number in
 * application order. glyphs/count is the live run state BEFORE that lookup
 * (snapshot semantics identical to pydwshape's DWriteCore hook). */
extern void wd_port_trace(unsigned int table_kind, unsigned int seq,
        const UINT16 *glyphs, unsigned int glyph_count);

/* ------------------------------------------------------------------ */
/* No-op debug macros (upstream used Wine's debug channel here)        */
/* ------------------------------------------------------------------ */

#define WINE_DEFAULT_DEBUG_CHANNEL(ch)
#define TRACE(...) do {} while (0)
#define WARN(...)  do {} while (0)
#define FIXME(...) do {} while (0)
#define ERR(...)   do {} while (0)

/* ------------------------------------------------------------------ */
/* Allocation helpers (upstream: dwrite_array_reserve in header)       */
/* ------------------------------------------------------------------ */

static inline BOOL dwrite_array_reserve(void **elements, size_t *capacity, size_t count, size_t size)
{
    size_t new_capacity, max_capacity;
    void *new_elements;

    if (count <= *capacity)
        return TRUE;

    max_capacity = ~(SIZE_T)0 / size;
    if (count > max_capacity)
        return FALSE;

    new_capacity = max((size_t)4, *capacity);
    while (new_capacity < count && new_capacity <= max_capacity / 2)
        new_capacity *= 2;
    if (new_capacity < count)
        new_capacity = max_capacity;

    new_elements = realloc(*elements, new_capacity * size);
    if (!new_elements)
        return FALSE;

    *elements = new_elements;
    *capacity = new_capacity;

    return TRUE;
}

#ifdef __cplusplus
}
#endif

#endif /* __WINE_DWRITE_PRIVATE_PORT_H */
