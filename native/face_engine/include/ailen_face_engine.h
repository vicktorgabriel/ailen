#ifndef AILEN_FACE_ENGINE_H
#define AILEN_FACE_ENGINE_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#if defined(AILEN_FACE_ENGINE_BUILD)
#define AILEN_FACE_API __declspec(dllexport)
#else
#define AILEN_FACE_API __declspec(dllimport)
#endif
#else
#define AILEN_FACE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
#define AILEN_FACE_NOEXCEPT noexcept
extern "C" {
#else
#define AILEN_FACE_NOEXCEPT
#endif

#define AILEN_FACE_ABI_MAJOR 1u
#define AILEN_FACE_ABI_MINOR 4u
#define AILEN_FACE_ABI_VERSION ((AILEN_FACE_ABI_MAJOR << 16u) | AILEN_FACE_ABI_MINOR)

typedef struct ailen_face_handle ailen_face_handle;

typedef enum ailen_face_result {
    AILEN_FACE_OK = 0,
    AILEN_FACE_INVALID_ARGUMENT = 1,
    AILEN_FACE_IO_ERROR = 2,
    AILEN_FACE_INVALID_PACK = 3,
    AILEN_FACE_INCOMPATIBLE = 4,
    AILEN_FACE_NOT_FOUND = 5,
    AILEN_FACE_BUSY = 6,
    AILEN_FACE_DECODE_ERROR = 7,
    AILEN_FACE_NOT_READY = 8,
    AILEN_FACE_INTERNAL_ERROR = 9
} ailen_face_result;

typedef enum ailen_face_pixel_format {
    AILEN_FACE_PIXEL_FORMAT_RGB24 = 1
} ailen_face_pixel_format;

typedef enum ailen_face_sequence_category {
    AILEN_FACE_SEQUENCE_STATE = 1,
    AILEN_FACE_SEQUENCE_MICROACTION = 2,
    AILEN_FACE_SEQUENCE_EMOTION = 3,
    AILEN_FACE_SEQUENCE_INTENSE_EMOTION = 4,
    AILEN_FACE_SEQUENCE_SPEECH = 5
} ailen_face_sequence_category;

typedef enum ailen_face_sequence_layer {
    AILEN_FACE_LAYER_FULL_FRAME = 1,
    AILEN_FACE_LAYER_MOUTH_ROI = 2,
    AILEN_FACE_LAYER_UPPER_FACE_ROI = 3
} ailen_face_sequence_layer;

typedef enum ailen_face_sequence_policy {
    AILEN_FACE_POLICY_CONVERSATIONAL = 1u << 5u,
    AILEN_FACE_POLICY_EXPLICIT_ONLY = 1u << 6u,
    AILEN_FACE_POLICY_STATE_CONTROLLED = 1u << 7u
} ailen_face_sequence_policy;

AILEN_FACE_API uint32_t ailen_face_get_abi_version(void) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API ailen_face_handle *ailen_face_create(void) AILEN_FACE_NOEXCEPT;
/* Caller must stop and join every thread using the handle before destroy. */
AILEN_FACE_API void ailen_face_destroy(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;

AILEN_FACE_API int ailen_face_load_pack(ailen_face_handle *handle, const char *path_utf8) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API void ailen_face_unload_pack(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_pack_id(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_pack_version(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;

AILEN_FACE_API size_t ailen_face_get_expression_count(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_expression(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_has_expression(ailen_face_handle *handle, const char *expression) AILEN_FACE_NOEXCEPT;

AILEN_FACE_API size_t ailen_face_get_sequence_count(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_sequence(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_sequence_category(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_sequence_layer(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_sequence_flags(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_sequence_duration_ms(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API size_t ailen_face_get_state_count(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_state(ailen_face_handle *handle, size_t index) AILEN_FACE_NOEXCEPT;

AILEN_FACE_API int ailen_face_set_state(ailen_face_handle *handle, const char *state) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_trigger_expression(
    ailen_face_handle *handle,
    const char *expression,
    uint32_t minimum_duration_ms
    ) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_clear_expression(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_trigger_microaction(
    ailen_face_handle *handle,
    const char *microaction
    ) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_set_intensity(ailen_face_handle *handle, float intensity) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_set_speech_level(ailen_face_handle *handle, float level) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_set_viseme(ailen_face_handle *handle, const char *viseme) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_set_gaze(ailen_face_handle *handle, float x, float y) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_set_random_seed(ailen_face_handle *handle, uint64_t seed) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_update(ailen_face_handle *handle, uint32_t delta_ms) AILEN_FACE_NOEXCEPT;

/*
 * Legacy snapshot API. The pointer is a thread-local copy, valid until the next
 * ailen_face_get_frame call on the same thread or until that thread exits.
 * New callers must use ailen_face_copy_frame, which is the canonical
 * concurrency-safe frame API.
 */
AILEN_FACE_API const uint8_t *ailen_face_get_frame(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API size_t ailen_face_get_frame_size(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API int ailen_face_copy_frame(
    ailen_face_handle *handle,
    uint8_t *destination,
    size_t destination_size
    ) AILEN_FACE_NOEXCEPT;
/*
 * Canonical presentation scaler. Produces aspect-preserving dimensions chosen
 * by the caller with native bilinear filtering; destination_stride may include
 * padding but must be at least destination_width * 3 bytes.
 */
AILEN_FACE_API int ailen_face_copy_frame_scaled(
    ailen_face_handle *handle,
    uint8_t *destination,
    size_t destination_size,
    uint32_t destination_width,
    uint32_t destination_height,
    size_t destination_stride
    ) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_width(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_height(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_stride(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint32_t ailen_face_get_pixel_format(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API uint64_t ailen_face_get_frame_generation(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_current_sequence(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;
AILEN_FACE_API const char *ailen_face_get_last_error(ailen_face_handle *handle) AILEN_FACE_NOEXCEPT;

#ifdef __cplusplus
}
#endif

#undef AILEN_FACE_NOEXCEPT

#endif
