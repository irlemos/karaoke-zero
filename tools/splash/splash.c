#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <time.h>
#include <math.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/fb.h>
#include <zlib.h>

#include "font8x16.h"

#ifndef FBIOBLANK
#define FBIOBLANK 0x4611
#endif
#ifndef VESA_NO_BLANKING
#define VESA_NO_BLANKING 0
#endif

static volatile sig_atomic_t g_running = 1;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

// Convert 32-bit ARGB (0xAARRGGBB) to target framebuffer pixel format
static inline uint32_t pack_pixel(uint32_t argb, const struct fb_var_screeninfo *vinfo) {
    if (vinfo->bits_per_pixel == 32) {
        uint8_t a = (argb >> 24) & 0xFF;
        uint8_t r = (argb >> 16) & 0xFF;
        uint8_t g = (argb >> 8) & 0xFF;
        uint8_t b = argb & 0xFF;

        return ((uint32_t)r << vinfo->red.offset) |
               ((uint32_t)g << vinfo->green.offset) |
               ((uint32_t)b << vinfo->blue.offset) |
               ((uint32_t)a << vinfo->transp.offset);
    } else if (vinfo->bits_per_pixel == 16) {
        // RGB565
        uint8_t r = (argb >> 19) & 0x1F;
        uint8_t g = (argb >> 10) & 0x3F;
        uint8_t b = (argb >> 3) & 0x1F;
        return (r << 11) | (g << 5) | b;
    }
    return argb;
}

static void draw_char(uint32_t *buf, int pitch, int width, int height,
                      int x, int y, char c, uint32_t color, int scale) {
    if (c < 32 || c > 126) c = ' ';
    const uint8_t *glyph = font8x16[c - 32];

    for (int row = 0; row < 16; row++) {
        uint8_t bits = glyph[row];
        for (int col = 0; col < 8; col++) {
            if (bits & (1 << (7 - col))) {
                for (int dy = 0; dy < scale; dy++) {
                    int py = y + row * scale + dy;
                    if (py < 0 || py >= height) continue;
                    for (int dx = 0; dx < scale; dx++) {
                        int px = x + col * scale + dx;
                        if (px < 0 || px >= width) continue;
                        buf[py * (pitch / 4) + px] = color;
                    }
                }
            }
        }
    }
}

static void draw_string_centered(uint32_t *buf, int pitch, int width, int height,
                                 int cx, int cy, const char *str, uint32_t color, int scale) {
    int len = strlen(str);
    int str_w = len * 8 * scale;
    int str_h = 16 * scale;
    int start_x = cx - (str_w / 2);
    int start_y = cy - (str_h / 2);

    for (int i = 0; i < len; i++) {
        draw_char(buf, pitch, width, height, start_x + (i * 8 * scale), start_y, str[i], color, scale);
    }
}

static void fill_rect(uint32_t *buf, int pitch, int width, int height,
                      int x1, int y1, int x2, int y2, uint32_t color) {
    if (x1 < 0) x1 = 0;
    if (y1 < 0) y1 = 0;
    if (x2 >= width) x2 = width - 1;
    if (y2 >= height) y2 = height - 1;
    if (x1 > x2 || y1 > y2) return;

    int p4 = pitch / 4;
    for (int y = y1; y <= y2; y++) {
        uint32_t *row = &buf[y * p4];
        for (int x = x1; x <= x2; x++) {
            row[x] = color;
        }
    }
}

static void draw_rounded_rect(uint32_t *buf, int pitch, int width, int height,
                              int x1, int y1, int x2, int y2, int radius, uint32_t color) {
    fill_rect(buf, pitch, width, height, x1 + radius, y1, x2 - radius, y2, color);
    fill_rect(buf, pitch, width, height, x1, y1 + radius, x1 + radius - 1, y2 - radius, color);
    fill_rect(buf, pitch, width, height, x2 - radius + 1, y1 + radius, x2, y2 - radius, color);

    int r2 = radius * radius;
    int p4 = pitch / 4;
    // Corners
    for (int dy = 0; dy < radius; dy++) {
        for (int dx = 0; dx < radius; dx++) {
            int ddx = radius - dx - 1;
            int ddy = radius - dy - 1;
            if (ddx * ddx + ddy * ddy <= r2) {
                // Top-Left
                int px = x1 + dx; int py = y1 + dy;
                if (px >= 0 && px < width && py >= 0 && py < height) buf[py * p4 + px] = color;
                // Top-Right
                px = x2 - dx; py = y1 + dy;
                if (px >= 0 && px < width && py >= 0 && py < height) buf[py * p4 + px] = color;
                // Bottom-Left
                px = x1 + dx; py = y2 - dy;
                if (px >= 0 && px < width && py >= 0 && py < height) buf[py * p4 + px] = color;
                // Bottom-Right
                px = x2 - dx; py = y2 - dy;
                if (px >= 0 && px < width && py >= 0 && py < height) buf[py * p4 + px] = color;
            }
        }
    }
}

static double get_elapsed_seconds(struct timespec *start) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (now.tv_sec - start->tv_sec) + (now.tv_nsec - start->tv_nsec) * 1e-9;
}

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;

    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    signal(SIGHUP, handle_signal);

    // 1. Open framebuffer device (retry for up to 3 seconds if initializing)
    int fbfd = -1;
    for (int retry = 0; retry < 30 && g_running; retry++) {
        fbfd = open("/dev/fb0", O_RDWR);
        if (fbfd >= 0) break;
        usleep(100000);
    }

    if (fbfd < 0) {
        perror("Failed to open /dev/fb0");
        return 1;
    }

    // Unblank screen
    ioctl(fbfd, FBIOBLANK, VESA_NO_BLANKING);

    struct fb_var_screeninfo vinfo;
    struct fb_fix_screeninfo finfo;

    if (ioctl(fbfd, FBIOGET_FSCREENINFO, &finfo) < 0 || ioctl(fbfd, FBIOGET_VSCREENINFO, &vinfo) < 0) {
        perror("Error reading framebuffer screen info");
        close(fbfd);
        return 1;
    }

    int width = vinfo.xres;
    int height = vinfo.yres;
    int bpp = vinfo.bits_per_pixel;
    int line_length = finfo.line_length;
    long screensize = height * line_length;

    if (bpp != 32 && bpp != 16) {
        fprintf(stderr, "Unsupported framebuffer depth: %d bpp\n", bpp);
        close(fbfd);
        return 1;
    }

    uint8_t *fbp = (uint8_t *)mmap(0, screensize, PROT_READ | PROT_WRITE, MAP_SHARED, fbfd, 0);
    if (fbp == MAP_FAILED) {
        perror("Failed to mmap framebuffer");
        close(fbfd);
        return 1;
    }

    // Allocate 32-bit RGBA background and backbuffer
    size_t num_pixels = (size_t)width * height;
    uint32_t *bg_buffer = (uint32_t *)malloc(num_pixels * sizeof(uint32_t));
    uint32_t *work_buffer = (uint32_t *)malloc(num_pixels * sizeof(uint32_t));

    if (!bg_buffer || !work_buffer) {
        fprintf(stderr, "Failed to allocate memory buffers\n");
        munmap(fbp, screensize);
        close(fbfd);
        return 1;
    }

    // 2. Load compressed background image if available
    const char *bg_paths[] = {
        "/opt/karaokezero/assets/splash_bg.bin",
        "assets/splash_bg.bin",
        "../assets/splash_bg.bin",
        NULL
    };

    bool bg_loaded = false;
    for (int i = 0; bg_paths[i] != NULL; i++) {
        FILE *fp = fopen(bg_paths[i], "rb");
        if (fp) {
            fseek(fp, 0, SEEK_END);
            long file_sz = ftell(fp);
            fseek(fp, 0, SEEK_SET);

            if (file_sz > 0 && width == 1920 && height == 1080) {
                uint8_t *comp_data = (uint8_t *)malloc(file_sz);
                if (comp_data && fread(comp_data, 1, file_sz, fp) == (size_t)file_sz) {
                    uLongf dest_len = num_pixels * sizeof(uint32_t);
                    if (uncompress((Bytef *)bg_buffer, &dest_len, comp_data, file_sz) == Z_OK) {
                        bg_loaded = true;
                    }
                }
                free(comp_data);
            }
            fclose(fp);
            if (bg_loaded) break;
        }
    }

    // Procedural fallback background if compressed file is absent or screen resolution differs
    if (!bg_loaded) {
        uint32_t c_top_r = 11, c_top_g = 15, c_top_b = 25;
        uint32_t c_bot_r = 18, c_bot_g = 24, c_bot_b = 40;

        for (int y = 0; y < height; y++) {
            float f = (float)y / height;
            uint32_t r = c_top_r + (uint32_t)(f * (c_bot_r - c_top_r));
            uint32_t g = c_top_g + (uint32_t)(f * (c_bot_g - c_top_g));
            uint32_t b = c_top_b + (uint32_t)(f * (c_bot_b - c_top_b));
            uint32_t color = (0xFF << 24) | (r << 16) | (g << 8) | b;
            for (int x = 0; x < width; x++) {
                bg_buffer[y * width + x] = color;
            }
        }

        // Top cyan accent line
        fill_rect(bg_buffer, width * 4, width, height, 0, 0, width - 1, 5, 0xFF00DCFF);

        // Titles
        int center_y = height / 2 - 40;
        draw_string_centered(bg_buffer, width * 4, width, height, width / 2, center_y - 60,
                             "K A R A O K E - Z E R O", 0xFFFFFFFF, 3);
        draw_string_centered(bg_buffer, width * 4, width, height, width / 2, center_y,
                             "STANDALONE OFFLINE KARAOKE APPLIANCE", 0xFF00DCFF, 1);

        // Specs footer
        draw_string_centered(bg_buffer, width * 4, width, height, width / 2, height - 70,
                             "Raspberry Pi Zero W  •  VideoCore IV GPU  •  Zero GUI Overhead",
                             0xFFA0AFCC, 1);
    }

    // Color definitions
    const uint32_t COLOR_CARD_BG = 0xFF161D30;
    const uint32_t COLOR_CARD_BORDER = 0xFF2D3A5C;
    const uint32_t COLOR_BAR_BG = 0xFF121826;
    const uint32_t COLOR_CYAN = 0xFF00DCFF;
    const uint32_t COLOR_YELLOW = 0xFFFACB15;
    const uint32_t COLOR_MUTED = 0xFFA0AFCC;
    const uint32_t COLOR_SHIMMER = 0xFFC8F5FF;

    // Progress bar and status pill metrics
    int center_y = height / 2 - 40;
    int pill_w = 640;
    int pill_h = 56;
    int pill_x1 = (width - pill_w) / 2;
    int pill_y1 = center_y + 80;
    int pill_x2 = pill_x1 + pill_w;
    int pill_y2 = pill_y1 + pill_h;

    int bar_w = 540;
    int bar_h = 14;
    int bar_x1 = (width - bar_w) / 2;
    int bar_y1 = pill_y2 + 24;
    int bar_x2 = bar_x1 + bar_w;
    int bar_y2 = bar_y1 + bar_h;

    int dirty_y1 = pill_y1 - 6;
    int dirty_y2 = bar_y2 + 48;
    if (dirty_y1 < 0) dirty_y1 = 0;
    if (dirty_y2 >= height) dirty_y2 = height - 1;

    // Copy initial full background to framebuffer
    memcpy(work_buffer, bg_buffer, num_pixels * sizeof(uint32_t));

    if (bpp == 32) {
        for (int y = 0; y < height; y++) {
            uint32_t *dst = (uint32_t *)(fbp + y * line_length);
            uint32_t *src = &bg_buffer[y * width];
            for (int x = 0; x < width; x++) {
                dst[x] = pack_pixel(src[x], &vinfo);
            }
        }
    } else if (bpp == 16) {
        for (int y = 0; y < height; y++) {
            uint16_t *dst = (uint16_t *)(fbp + y * line_length);
            uint32_t *src = &bg_buffer[y * width];
            for (int x = 0; x < width; x++) {
                dst[x] = (uint16_t)pack_pixel(src[x], &vinfo);
            }
        }
    }

    struct timespec start_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);

    // 3. Fluid animation loop (25 fps = 40ms per frame)
    while (g_running) {
        double elapsed = get_elapsed_seconds(&start_time);

        // Progress curve calculation (0.10 to 0.94)
        float progress = 0.10f;
        const char *stage_text = "INITIALIZING HARDWARE SUBSYSTEMS";

        if (elapsed < 4.5) {
            float r = (float)(elapsed / 4.5);
            progress = 0.10f + 0.18f * (0.5f - 0.5f * cosf(r * 3.14159f));
            stage_text = "INITIALIZING HARDWARE SUBSYSTEMS";
        } else if (elapsed < 11.0) {
            float r = (float)((elapsed - 4.5) / 6.5);
            progress = 0.28f + 0.22f * (0.5f - 0.5f * cosf(r * 3.14159f));
            stage_text = "LOADING LINUX SYSTEM DAEMONS";
        } else if (elapsed < 19.0) {
            float r = (float)((elapsed - 11.0) / 8.0);
            progress = 0.50f + 0.25f * (0.5f - 0.5f * cosf(r * 3.14159f));
            stage_text = "MOUNTING STORAGE & MEDIA LIBRARY";
        } else if (elapsed < 29.0) {
            float r = (float)((elapsed - 19.0) / 10.0);
            progress = 0.75f + 0.17f * (0.5f - 0.5f * cosf(r * 3.14159f));
            stage_text = "STARTING PIKARAOKE APPLIANCE";
        } else {
            progress = 0.94f;
            stage_text = "AWAITING SERVICE READINESS";
        }

        // Restore dirty scanlines from static background
        for (int y = dirty_y1; y <= dirty_y2; y++) {
            memcpy(&work_buffer[y * width], &bg_buffer[y * width], width * sizeof(uint32_t));
        }

        // Draw status pill box outline and background
        draw_rounded_rect(work_buffer, width * 4, width, height,
                          pill_x1 - 1, pill_y1 - 1, pill_x2 + 1, pill_y2 + 1, 17, COLOR_CARD_BORDER);
        draw_rounded_rect(work_buffer, width * 4, width, height,
                          pill_x1, pill_y1, pill_x2, pill_y2, 16, COLOR_CARD_BG);
        draw_string_centered(work_buffer, width * 4, width, height,
                             width / 2, pill_y1 + pill_h / 2, stage_text, COLOR_YELLOW, 1);

        // Draw progress bar track
        draw_rounded_rect(work_buffer, width * 4, width, height,
                          bar_x1, bar_y1, bar_x2, bar_y2, 7, COLOR_BAR_BG);

        // Draw progress fill
        int fill_w = (int)(bar_w * progress);
        if (fill_w < 10) fill_w = 10;
        draw_rounded_rect(work_buffer, width * 4, width, height,
                          bar_x1, bar_y1, bar_x1 + fill_w, bar_y2, 7, COLOR_CYAN);

        // Animated glowing shimmer pulse sweeping across the bar every 1.4 seconds
        double shimmer_period = 1.4;
        double shimmer_phase = fmod(elapsed, shimmer_period) / shimmer_period;
        int shimmer_center = bar_x1 + (int)(shimmer_phase * (fill_w + 60)) - 30;
        int shimmer_width = 36;
        int s_x1 = shimmer_center - (shimmer_width / 2);
        int s_x2 = shimmer_center + (shimmer_width / 2);
        if (s_x1 < bar_x1) s_x1 = bar_x1;
        if (s_x2 > bar_x1 + fill_w) s_x2 = bar_x1 + fill_w;

        if (s_x2 > s_x1) {
            fill_rect(work_buffer, width * 4, width, height,
                      s_x1, bar_y1 + 1, s_x2, bar_y2 - 1, COLOR_SHIMMER);
        }

        // Percentage text below bar
        char pct_str[48];
        snprintf(pct_str, sizeof(pct_str), "SYSTEM INITIALIZING  •  %d%%", (int)(progress * 100));
        draw_string_centered(work_buffer, width * 4, width, height,
                             width / 2, bar_y2 + 22, pct_str, COLOR_MUTED, 1);

        // Blit dirty scanlines to hardware framebuffer
        if (bpp == 32) {
            for (int y = dirty_y1; y <= dirty_y2; y++) {
                uint32_t *dst = (uint32_t *)(fbp + y * line_length);
                uint32_t *src = &work_buffer[y * width];
                for (int x = 0; x < width; x++) {
                    dst[x] = pack_pixel(src[x], &vinfo);
                }
            }
        } else if (bpp == 16) {
            for (int y = dirty_y1; y <= dirty_y2; y++) {
                uint16_t *dst = (uint16_t *)(fbp + y * line_length);
                uint32_t *src = &work_buffer[y * width];
                for (int x = 0; x < width; x++) {
                    dst[x] = (uint16_t)pack_pixel(src[x], &vinfo);
                }
            }
        }

        // Sleep 40ms (25 fps)
        usleep(40000);
    }

    // Cleanup on exit
    free(bg_buffer);
    free(work_buffer);
    munmap(fbp, screensize);
    close(fbfd);

    return 0;
}
