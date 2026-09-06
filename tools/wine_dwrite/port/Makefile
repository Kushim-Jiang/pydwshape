# Portable build for the Wine DWrite shaping port (Linux/macOS/*BSD).
# The same sources build on Windows via port/build.ps1 (MinGW).
#
# Targets:
#   all / wdmain  — CLI driver executable
#   lib           — shared library (libwinedwrite.so / .dylib)
#   clean
CC      ?= cc
CFLAGS  ?= -std=c11 -O2 -Wall -fPIC
INC     := -Iinclude -Isrc
SRC     := opentype_shaping.c shape_port.c mirror.c arabic.c arabic_table.c \
           wd_font.c wd_script.c wd_engine.c wd_json.c
OBJ     := $(SRC:.c=.o)

UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
SHLIB   := libwinedwrite.dylib
SHFLAGS := -dynamiclib
else
SHLIB   := libwinedwrite.so
SHFLAGS := -shared
endif

all: wdmain

wdmain: $(OBJ) main.o
	$(CC) $(OBJ) main.o -o $@ -lm

lib: $(OBJ)
	$(CC) $(SHFLAGS) -o $(SHLIB) $(OBJ) -lm

%.o: src/%.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@

clean:
	rm -f *.o wdmain $(SHLIB)

.PHONY: all lib clean
