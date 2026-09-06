/*
 * windef.h — PORT shim stand-in for Wine's windef.h.
 *
 * Wine data-only translation units (e.g. shapers/arabic_table.c) include
 * Wine's windef.h purely for base integer typedefs. The shaping engine units
 * include dwrite_private.h instead (which provides the same types). This shim
 * keeps those data files compiling with no Windows headers.
 *
 * If a TU ever includes BOTH this and dwrite_private.h, the typedefs below are
 * identical redefinitions, which C11 permits.
 */
#ifndef __WINDEF_PORT_H
#define __WINDEF_PORT_H

#include <stddef.h>
#include <stdint.h>

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
typedef int32_t  SHORT;

#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif

#ifndef min
#define min(a, b) (((a) < (b)) ? (a) : (b))
#endif
#ifndef max
#define max(a, b) (((a) > (b)) ? (a) : (b))
#endif

#endif /* __WINDEF_PORT_H */
