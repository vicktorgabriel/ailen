#include "ailen_face_engine.h"

#include <algorithm>
#include <array>
#include <csetjmp>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

extern "C" {
#include <jpeglib.h>
}

namespace {

thread_local std::array<char, 512> abi_text_buffer{};
thread_local std::vector<uint8_t> abi_frame_snapshot{};

const char* copy_abi_text(const char* value) noexcept {
    const char* source = value != nullptr ? value : "";
    size_t length = 0;
    while (source[length] != '\0' && length + 1U < abi_text_buffer.size()) {
        ++length;
    }
    std::memcpy(abi_text_buffer.data(), source, length);
    abi_text_buffer[length] = '\0';
    return abi_text_buffer.data();
}

constexpr std::array<uint8_t, 8> kMagic{{'A', 'I', 'L', 'E', 'N', 'F', 'P', 0}};
constexpr uint16_t kFormatMajor = 1;
constexpr uint16_t kFormatMinor = 6;
constexpr uint16_t kHeaderSize = 176;
constexpr uint32_t kPixelFormatRgb24 = 1;
constexpr uint64_t kMaxPackBytes = 512ULL * 1024ULL * 1024ULL;
constexpr uint32_t kMaxDimension = 4096;
constexpr uint32_t kMaxSequences = 4096;
constexpr uint32_t kMaxFrames = 200000;
constexpr uint32_t kMaxStates = 256;
constexpr uint32_t kMaxActions = 8192;
constexpr float kMaxSequenceWeight = 1000.0F;
constexpr uint64_t kSequenceRecordSize = 112;
constexpr uint64_t kFrameRecordSize = 48;
constexpr uint64_t kStateRecordSize = 48;
constexpr uint64_t kActionRecordSize = 16;

constexpr uint32_t kCategoryState = 1;
constexpr uint32_t kCategoryMicroaction = 2;
constexpr uint32_t kCategoryEmotion = 3;
constexpr uint32_t kCategoryIntenseEmotion = 4;
constexpr uint32_t kCategorySpeech = 5;
constexpr uint32_t kLayerFullFrame = 1;
constexpr uint32_t kLayerMouthRoi = 2;
constexpr uint32_t kLayerUpperFaceRoi = 3;
constexpr uint32_t kFlagLoopable = 1U << 0U;
constexpr uint32_t kFlagInterruptible = 1U << 1U;
constexpr uint32_t kFlagSpeechCompatible = 1U << 2U;
constexpr uint32_t kFlagGazeCompatible = 1U << 3U;
constexpr uint32_t kFlagConversational = 1U << 5U;
constexpr uint32_t kFlagExplicitOnly = 1U << 6U;
constexpr uint32_t kFlagStateControlled = 1U << 7U;
constexpr uint32_t kFlagGazeLeft = 1U << 8U;
constexpr uint32_t kFlagGazeRight = 1U << 9U;
constexpr uint32_t kFlagGazeUp = 1U << 10U;
constexpr uint32_t kFlagGazeDown = 1U << 11U;
constexpr uint32_t kFlagDeltaBlend = 1U << 12U;
constexpr uint32_t kFrameFaceTransform = 1U << 31U;
constexpr uint32_t kFrameFaceTransformReserved = 1U << 30U;
constexpr uint32_t kGazeDirectionMask =
    kFlagGazeLeft | kFlagGazeRight | kFlagGazeUp | kFlagGazeDown;
constexpr uint32_t kAffectPolicyMask =
    kFlagConversational | kFlagExplicitOnly | kFlagStateControlled;

constexpr uint32_t kSpeechStyleAutomatic = 0;
constexpr uint32_t kSpeechStyleSoft = 1;
constexpr uint32_t kSpeechStyleNormal = 2;
constexpr uint32_t kSpeechStyleExpressive = 3;
constexpr uint32_t kSpeechStyleHappy = 4;
constexpr uint32_t kSpeechStyleSerious = 5;
constexpr uint32_t kMaxSpeechStyle = kSpeechStyleSerious;

struct Header {
    uint16_t format_major{};
    uint16_t format_minor{};
    uint16_t header_size{};
    uint16_t required_abi{};
    uint32_t flags{};
    uint32_t width{};
    uint32_t height{};
    uint32_t pixel_format{};
    uint32_t sequence_count{};
    uint32_t frame_count{};
    uint32_t state_count{};
    uint32_t action_count{};
    uint64_t sequence_offset{};
    uint64_t sequence_size{};
    uint64_t frame_offset{};
    uint64_t frame_size{};
    uint64_t state_offset{};
    uint64_t state_size{};
    uint64_t action_offset{};
    uint64_t action_size{};
    uint64_t string_offset{};
    uint64_t string_size{};
    uint64_t payload_offset{};
    uint64_t payload_size{};
    uint64_t file_size{};
    uint32_t metadata_crc{};
    uint32_t payload_crc{};
    uint32_t pack_id_offset{};
    uint32_t pack_id_length{};
    uint32_t pack_version_offset{};
    uint32_t pack_version_length{};
};

struct Sequence {
    std::string id;
    std::string return_state;
    uint32_t category{};
    uint32_t layer{};
    uint32_t flags{};
    int32_t priority{};
    float intensity{};
    float weight{};
    uint32_t fps_num{};
    uint32_t fps_den{};
    uint32_t first_frame{};
    uint32_t frame_count{};
    uint32_t entry{};
    uint32_t onset{};
    uint32_t peak{};
    uint32_t hold_start{};
    uint32_t hold_end{};
    uint32_t exit{};
    uint32_t roi_x{};
    uint32_t roi_y{};
    uint32_t roi_width{};
    uint32_t roi_height{};
    uint32_t transition_in_ms{};
    uint32_t transition_out_ms{};
    uint32_t cooldown_ms{};
    uint32_t speech_style{};
};

struct Frame {
    uint32_t sequence_index{};
    uint32_t local_index{};
    uint32_t timestamp_ms{};
    uint32_t encoding{};
    uint32_t width{};
    uint32_t height{};
    uint64_t payload_offset{};
    uint32_t payload_size{};
    uint32_t decoded_size{};
    uint32_t crc32{};
    uint32_t flags{};
};

struct FaceTransform {
    float translate_x{};
    float translate_y{};
    float angle_radians{};
    float scale{1.0F};
};

int32_t unpack_signed(uint32_t value, uint32_t bits) {
    const uint32_t sign = 1U << (bits - 1U);
    const uint32_t mask = (1U << bits) - 1U;
    const uint32_t bounded = value & mask;
    return (bounded & sign) != 0U
        ? static_cast<int32_t>(bounded) - static_cast<int32_t>(1U << bits)
        : static_cast<int32_t>(bounded);
}

FaceTransform decode_face_transform(uint32_t flags) {
    constexpr float kPi = 3.14159265358979323846F;
    FaceTransform result{};
    if ((flags & kFrameFaceTransform) == 0U) {
        return result;
    }
    result.translate_x = static_cast<float>(unpack_signed(flags, 8));
    result.translate_y = static_cast<float>(unpack_signed(flags >> 8U, 8));
    const float angle_degrees = static_cast<float>(unpack_signed(flags >> 16U, 7)) / 2.0F;
    result.angle_radians = angle_degrees * kPi / 180.0F;
    result.scale = 1.0F + static_cast<float>(unpack_signed(flags >> 23U, 7)) / 128.0F;
    return result;
}

struct StateAction {
    uint32_t sequence_index{};
    uint32_t weight_milli{};
    uint32_t cooldown_ms{};
    uint32_t flags{};
};

struct State {
    std::string id;
    uint32_t base_sequence{};
    uint32_t first_action{};
    uint32_t action_count{};
    uint32_t wait_min_ms{};
    uint32_t wait_max_ms{};
    uint32_t flags{};
};

class Reader {
public:
    Reader(const uint8_t* data, size_t size) : data_(data), size_(size) {}

    bool skip(size_t count) {
        if (count > size_ - position_) {
            return false;
        }
        position_ += count;
        return true;
    }

    bool u16(uint16_t& value) {
        if (!available(2)) {
            return false;
        }
        value = static_cast<uint16_t>(data_[position_]) |
                static_cast<uint16_t>(data_[position_ + 1]) << 8U;
        position_ += 2;
        return true;
    }

    bool u32(uint32_t& value) {
        if (!available(4)) {
            return false;
        }
        value = static_cast<uint32_t>(data_[position_]) |
                static_cast<uint32_t>(data_[position_ + 1]) << 8U |
                static_cast<uint32_t>(data_[position_ + 2]) << 16U |
                static_cast<uint32_t>(data_[position_ + 3]) << 24U;
        position_ += 4;
        return true;
    }

    bool i32(int32_t& value) {
        uint32_t raw = 0;
        if (!u32(raw)) {
            return false;
        }
        std::memcpy(&value, &raw, sizeof(value));
        return true;
    }

    bool u64(uint64_t& value) {
        uint32_t low = 0;
        uint32_t high = 0;
        if (!u32(low) || !u32(high)) {
            return false;
        }
        value = static_cast<uint64_t>(low) | static_cast<uint64_t>(high) << 32U;
        return true;
    }

    bool f32(float& value) {
        uint32_t raw = 0;
        if (!u32(raw)) {
            return false;
        }
        std::memcpy(&value, &raw, sizeof(value));
        return std::isfinite(value);
    }

private:
    bool available(size_t count) const {
        return position_ <= size_ && count <= size_ - position_;
    }

    const uint8_t* data_{};
    size_t size_{};
    size_t position_{};
};

const std::array<uint32_t, 256>& crc_table() {
    static const std::array<uint32_t, 256> table = [] {
        std::array<uint32_t, 256> values{};
        for (uint32_t index = 0; index < values.size(); ++index) {
            uint32_t value = index;
            for (int bit = 0; bit < 8; ++bit) {
                value = (value & 1U) != 0U ? 0xEDB88320U ^ (value >> 1U) : value >> 1U;
            }
            values[index] = value;
        }
        return values;
    }();
    return table;
}

uint32_t crc32_update(uint32_t previous, const uint8_t* data, size_t size) {
    uint32_t value = ~previous;
    const auto& table = crc_table();
    for (size_t index = 0; index < size; ++index) {
        value = table[(value ^ data[index]) & 0xFFU] ^ (value >> 8U);
    }
    return ~value;
}

bool checked_span(uint64_t offset, uint64_t size, uint64_t file_size) {
    return offset >= kHeaderSize && offset <= file_size && size <= file_size - offset;
}

struct JpegErrorManager {
    jpeg_error_mgr base{};
    jmp_buf jump{};
    char message[JMSG_LENGTH_MAX]{};
};

void jpeg_error_exit(j_common_ptr info) {
    auto* error = reinterpret_cast<JpegErrorManager*>(info->err);
    (*info->err->format_message)(info, error->message);
    longjmp(error->jump, 1);
}

bool decode_jpeg(
    const std::vector<uint8_t>& encoded,
    uint32_t expected_width,
    uint32_t expected_height,
    std::vector<uint8_t>& decoded,
    std::string& error_text
) {
    jpeg_decompress_struct decoder{};
    JpegErrorManager error{};
    decoder.err = jpeg_std_error(&error.base);
    error.base.error_exit = jpeg_error_exit;
    if (setjmp(error.jump) != 0) {
        jpeg_destroy_decompress(&decoder);
        error_text = std::string("JPEG decode failed: ") + error.message;
        return false;
    }
    jpeg_create_decompress(&decoder);
    jpeg_mem_src(
        &decoder,
        const_cast<unsigned char*>(encoded.data()),
        static_cast<unsigned long>(encoded.size())
    );
    jpeg_read_header(&decoder, TRUE);
    decoder.out_color_space = JCS_RGB;
    jpeg_start_decompress(&decoder);
    if (decoder.output_width != expected_width || decoder.output_height != expected_height ||
        decoder.output_components != 3) {
        jpeg_destroy_decompress(&decoder);
        error_text = "JPEG dimensions or color space do not match the frame table";
        return false;
    }
    const size_t stride = static_cast<size_t>(expected_width) * 3U;
    decoded.resize(stride * expected_height);
    while (decoder.output_scanline < decoder.output_height) {
        JSAMPROW row = decoded.data() + static_cast<size_t>(decoder.output_scanline) * stride;
        jpeg_read_scanlines(&decoder, &row, 1);
    }
    jpeg_finish_decompress(&decoder);
    jpeg_destroy_decompress(&decoder);
    return true;
}

class Engine {
public:
    int load(const char* path) {
        if (path == nullptr || path[0] == '\0') {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "FacePack path is empty");
        }
        unload_locked();
        stream_.open(std::filesystem::u8path(path), std::ios::binary);
        if (!stream_.is_open()) {
            return fail(AILEN_FACE_IO_ERROR, "could not open FacePack");
        }
        stream_.seekg(0, std::ios::end);
        const std::streamoff end = stream_.tellg();
        if (end < static_cast<std::streamoff>(kHeaderSize) ||
            static_cast<uint64_t>(end) > kMaxPackBytes) {
            unload_locked();
            return fail(AILEN_FACE_INVALID_PACK, "FacePack file size is outside safety limits");
        }
        const uint64_t actual_file_size = static_cast<uint64_t>(end);
        std::vector<uint8_t> header_bytes(kHeaderSize);
        if (!read_at(0, header_bytes.data(), header_bytes.size())) {
            unload_locked();
            return fail(AILEN_FACE_IO_ERROR, "could not read FacePack header");
        }
        if (!parse_header(header_bytes, actual_file_size)) {
            unload_locked();
            return last_result_;
        }
        const uint64_t metadata_size = header_.payload_offset - header_.sequence_offset;
        if (metadata_size > kMaxPackBytes) {
            unload_locked();
            return fail(AILEN_FACE_INVALID_PACK, "FacePack metadata is too large");
        }
        metadata_.resize(static_cast<size_t>(metadata_size));
        if (!read_at(header_.sequence_offset, metadata_.data(), metadata_.size())) {
            unload_locked();
            return fail(AILEN_FACE_IO_ERROR, "could not read FacePack metadata");
        }
        if (crc32_update(0, metadata_.data(), metadata_.size()) != header_.metadata_crc) {
            unload_locked();
            return fail(AILEN_FACE_INVALID_PACK, "FacePack metadata checksum does not match");
        }
        uint32_t payload_crc = 0;
        if (!crc_range(header_.payload_offset, header_.payload_size, payload_crc)) {
            unload_locked();
            return fail(AILEN_FACE_IO_ERROR, "could not checksum FacePack payload");
        }
        if (payload_crc != header_.payload_crc) {
            unload_locked();
            return fail(AILEN_FACE_INVALID_PACK, "FacePack payload checksum does not match");
        }
        if (!parse_tables()) {
            unload_locked();
            return last_result_;
        }
        output_.assign(static_cast<size_t>(header_.width) * header_.height * 3U, 0);
        last_trigger_ms_.assign(sequences_.size(), 0);
        has_triggered_.assign(sequences_.size(), false);
        loaded_ = true;
        current_state_ = 0;
        for (size_t index = 0; index < states_.size(); ++index) {
            if (states_[index].id == "idle") {
                current_state_ = static_cast<int64_t>(index);
                break;
            }
        }
        schedule_next_action();
        if (!render_current()) {
            const int result = last_result_;
            unload_locked();
            return result;
        }
        last_result_ = AILEN_FACE_OK;
        last_error_.clear();
        return AILEN_FACE_OK;
    }

    void unload_locked() {
        if (stream_.is_open()) {
            stream_.close();
        }
        stream_.clear();
        loaded_ = false;
        header_ = Header{};
        metadata_.clear();
        strings_.clear();
        sequences_.clear();
        frames_.clear();
        states_.clear();
        actions_.clear();
        expressions_.clear();
        pack_id_.clear();
        pack_version_.clear();
        output_.clear();
        base_cache_.clear();
        upper_cache_.clear();
        speech_cache_.clear();
        last_base_frame_ = -1;
        last_upper_frame_ = -1;
        last_speech_frame_ = -1;
        last_render_base_frame_ = -1;
        last_render_upper_frame_ = -1;
        last_render_speech_frame_ = -1;
        last_render_speech_strength_ = -1;
        frame_generation_ = 0;
        current_state_ = -1;
        active_expression_ = -1;
        active_action_ = -1;
        active_upper_action_ = -1;
        default_speech_sequence_ = -1;
        active_speech_sequence_ = -1;
        current_sequence_cache_.clear();
        total_ms_ = 0;
        state_elapsed_ms_ = 0;
        expression_elapsed_ms_ = 0;
        action_elapsed_ms_ = 0;
        upper_elapsed_ms_ = 0;
        speech_elapsed_ms_ = 0;
        expression_minimum_ms_ = 0;
        next_action_at_ms_ = 0;
        intensity_ = 1.0F;
        has_intensity_override_ = false;
        speech_level_ = 0.0F;
        gaze_x_ = 0.0F;
        gaze_y_ = 0.0F;
        speech_manual_ = false;
        upper_is_explicit_gaze_ = false;
        last_trigger_ms_.clear();
        has_triggered_.clear();
    }

    int set_state(const char* state) {
        if (!ready()) {
            return last_result_;
        }
        if (state == nullptr || state[0] == '\0') {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "state is empty");
        }
        const int64_t index = find_state(state);
        if (index < 0) {
            return fail(AILEN_FACE_NOT_FOUND, std::string("unknown FacePack state: ") + state);
        }
        current_state_ = index;
        state_elapsed_ms_ = 0;
        active_action_ = -1;
        active_upper_action_ = -1;
        action_elapsed_ms_ = 0;
        upper_elapsed_ms_ = 0;
        upper_is_explicit_gaze_ = false;
        schedule_next_action();
        clear_error();
        return AILEN_FACE_OK;
    }

    int trigger_expression(const char* expression, uint32_t minimum_duration_ms) {
        if (!ready()) {
            return last_result_;
        }
        if (expression == nullptr || expression[0] == '\0') {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "expression is empty");
        }
        const int64_t index = find_expression(expression);
        if (index < 0) {
            return fail(
                AILEN_FACE_NOT_FOUND,
                std::string("unknown FacePack expression: ") + expression
            );
        }
        if (active_expression_ >= 0) {
            const Sequence& active = sequences_[static_cast<size_t>(active_expression_)];
            const Sequence& requested = sequences_[static_cast<size_t>(index)];
            if ((active.flags & kFlagInterruptible) == 0U) {
                return fail(AILEN_FACE_BUSY, "active expression is not interruptible");
            }
            if (requested.priority < active.priority) {
                return fail(AILEN_FACE_BUSY, "requested expression has lower priority");
            }
        }
        active_expression_ = index;
        active_action_ = -1;
        if ((sequences_[static_cast<size_t>(index)].flags & kFlagGazeCompatible) == 0U) {
            active_upper_action_ = -1;
            upper_elapsed_ms_ = 0;
            upper_is_explicit_gaze_ = false;
        }
        expression_elapsed_ms_ = 0;
        expression_minimum_ms_ = std::min<uint32_t>(minimum_duration_ms, 10000U);
        if (!speech_manual_) {
            select_automatic_speech(speech_level_);
        }
        if (active_upper_action_ < 0) {
            schedule_next_action();
        }
        clear_error();
        return AILEN_FACE_OK;
    }

    int clear_expression() {
        if (!ready()) {
            return last_result_;
        }
        active_expression_ = -1;
        expression_elapsed_ms_ = 0;
        expression_minimum_ms_ = 0;
        if (!speech_manual_) {
            select_automatic_speech(speech_level_);
        }
        schedule_next_action();
        clear_error();
        return AILEN_FACE_OK;
    }

    int trigger_microaction(const char* microaction) {
        if (!ready()) {
            return last_result_;
        }
        if (microaction == nullptr || microaction[0] == '\0') {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "microaction is empty");
        }
        const int64_t index = find_sequence(microaction);
        if (index < 0 ||
            sequences_[static_cast<size_t>(index)].category != kCategoryMicroaction) {
            return fail(
                AILEN_FACE_NOT_FOUND,
                std::string("unknown FacePack microaction: ") + microaction
            );
        }
        const Sequence& sequence = sequences_[static_cast<size_t>(index)];
        if (sequence.layer == kLayerUpperFaceRoi) {
            if (!current_base_allows_upper_face()) {
                return fail(AILEN_FACE_BUSY, "current visual base does not allow upper-face layers");
            }
            active_upper_action_ = index;
            upper_elapsed_ms_ = 0;
            upper_is_explicit_gaze_ = false;
        } else {
            if (active_expression_ >= 0) {
                return fail(AILEN_FACE_BUSY, "full-frame microaction cannot replace an expression");
            }
            active_action_ = index;
            action_elapsed_ms_ = 0;
        }
        clear_error();
        return AILEN_FACE_OK;
    }

    int set_intensity(float value) {
        if (!ready()) {
            return last_result_;
        }
        if (!std::isfinite(value)) {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "expression intensity is not finite");
        }
        intensity_ = std::clamp(value, 0.0F, 1.0F);
        has_intensity_override_ = true;
        clear_error();
        return AILEN_FACE_OK;
    }

    int set_speech(float value) {
        if (!ready()) {
            return last_result_;
        }
        if (!std::isfinite(value)) {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "speech level is not finite");
        }
        const float bounded = std::clamp(value, 0.0F, 1.0F);
        if (bounded <= 0.0F) {
            speech_elapsed_ms_ = 0;
        } else if (speech_level_ <= 0.0F && !speech_manual_) {
            select_automatic_speech(bounded);
        }
        speech_level_ = bounded;
        clear_error();
        return AILEN_FACE_OK;
    }

    int set_viseme(const char* viseme) {
        if (!ready()) {
            return last_result_;
        }
        if (viseme == nullptr || viseme[0] == '\0') {
            speech_manual_ = false;
            select_automatic_speech(speech_level_);
            clear_error();
            return AILEN_FACE_OK;
        }
        for (size_t index = 0; index < sequences_.size(); ++index) {
            const Sequence& sequence = sequences_[index];
            if (sequence.category == kCategorySpeech &&
                (sequence.layer == kLayerFullFrame || sequence.layer == kLayerMouthRoi) &&
                sequence.id == viseme) {
                active_speech_sequence_ = static_cast<int64_t>(index);
                speech_elapsed_ms_ = 0;
                speech_manual_ = true;
                clear_error();
                return AILEN_FACE_OK;
            }
        }
        return fail(AILEN_FACE_NOT_FOUND, std::string("unknown speech sequence: ") + viseme);
    }

    int set_gaze(float x, float y) {
        if (!ready()) {
            return last_result_;
        }
        if (!std::isfinite(x) || !std::isfinite(y)) {
            return fail(AILEN_FACE_INVALID_ARGUMENT, "gaze is not finite");
        }
        gaze_x_ = std::clamp(x, -1.0F, 1.0F);
        gaze_y_ = std::clamp(y, -1.0F, 1.0F);
        uint32_t direction = 0;
        const float magnitude = std::max(std::abs(gaze_x_), std::abs(gaze_y_));
        if (magnitude > 0.45F) {
            if (std::abs(gaze_x_) >= std::abs(gaze_y_)) {
                direction = gaze_x_ < 0.0F ? kFlagGazeLeft : kFlagGazeRight;
            } else {
                direction = gaze_y_ > 0.0F ? kFlagGazeUp : kFlagGazeDown;
            }
        }
        if (direction == 0) {
            if (upper_is_explicit_gaze_) {
                active_upper_action_ = -1;
                upper_elapsed_ms_ = 0;
                upper_is_explicit_gaze_ = false;
            }
        } else if (current_base_allows_upper_face()) {
            const int64_t index = find_gaze_sequence(direction, magnitude);
            if (index >= 0) {
                active_upper_action_ = index;
                upper_elapsed_ms_ = 0;
                upper_is_explicit_gaze_ = true;
            }
        }
        clear_error();
        return AILEN_FACE_OK;
    }

    int set_seed(uint64_t seed) {
        rng_state_ = seed == 0 ? 0x9E3779B97F4A7C15ULL : seed;
        if (loaded_) {
            schedule_next_action();
        }
        clear_error();
        return AILEN_FACE_OK;
    }

    int update(uint32_t delta_ms) {
        if (!ready()) {
            return last_result_;
        }
        total_ms_ += delta_ms;
        state_elapsed_ms_ += delta_ms;
        if (speech_level_ > 0.0F) {
            speech_elapsed_ms_ += delta_ms;
        }

        if (active_expression_ >= 0) {
            expression_elapsed_ms_ += delta_ms;
            const Sequence& sequence = sequences_[static_cast<size_t>(active_expression_)];
            if (expression_elapsed_ms_ >= playback_duration(sequence, true)) {
                const bool declared_return_matches =
                    current_state_ >= 0 &&
                    states_[static_cast<size_t>(current_state_)].id == sequence.return_state;
                active_expression_ = -1;
                expression_elapsed_ms_ = 0;
                expression_minimum_ms_ = 0;
                if (declared_return_matches) {
                    state_elapsed_ms_ = 0;
                }
                if (!speech_manual_) {
                    select_automatic_speech(speech_level_);
                }
                if (active_upper_action_ < 0) {
                    schedule_next_action();
                }
            }
        }
        if (active_expression_ < 0 && active_action_ >= 0) {
            action_elapsed_ms_ += delta_ms;
            const Sequence& sequence = sequences_[static_cast<size_t>(active_action_)];
            if (action_elapsed_ms_ >= playback_duration(sequence, false)) {
                active_action_ = -1;
                action_elapsed_ms_ = 0;
                schedule_next_action();
            }
        }
        if (active_upper_action_ >= 0) {
            upper_elapsed_ms_ += delta_ms;
            const Sequence& sequence = sequences_[static_cast<size_t>(active_upper_action_)];
            if (upper_elapsed_ms_ >= playback_duration(sequence, false)) {
                active_upper_action_ = -1;
                upper_elapsed_ms_ = 0;
                upper_is_explicit_gaze_ = false;
                schedule_next_action();
            }
        }
        if (active_action_ < 0 && active_upper_action_ < 0 && total_ms_ >= next_action_at_ms_) {
            choose_state_action();
        }

        if (!render_current()) {
            return last_result_;
        }
        clear_error();
        return AILEN_FACE_OK;
    }

    bool loaded() const { return loaded_; }
    uint32_t width() const { return loaded_ ? header_.width : 0; }
    uint32_t height() const { return loaded_ ? header_.height : 0; }
    uint32_t stride() const { return loaded_ ? header_.width * 3U : 0; }
    uint32_t pixel_format() const { return loaded_ ? header_.pixel_format : 0; }
    uint64_t frame_generation() const { return frame_generation_; }
    const std::vector<uint8_t>& output() const { return output_; }
    const std::string& pack_id() const { return pack_id_; }
    const std::string& pack_version() const { return pack_version_; }
    const std::string& error() const { return last_error_; }
    size_t expression_count() const { return expressions_.size(); }

    const char* expression_at(size_t index) const {
        if (index >= expressions_.size()) {
            return nullptr;
        }
        return sequences_[expressions_[index]].id.c_str();
    }

    int has_expression(const char* expression) const {
        return expression != nullptr && find_expression(expression) >= 0 ? 1 : 0;
    }

    size_t sequence_count() const { return sequences_.size(); }

    const char* sequence_at(size_t index) const {
        return index < sequences_.size() ? sequences_[index].id.c_str() : nullptr;
    }

    uint32_t sequence_category_at(size_t index) const {
        return index < sequences_.size() ? sequences_[index].category : 0U;
    }

    uint32_t sequence_layer_at(size_t index) const {
        return index < sequences_.size() ? sequences_[index].layer : 0U;
    }

    uint32_t sequence_flags_at(size_t index) const {
        return index < sequences_.size() ? sequences_[index].flags : 0U;
    }

    uint32_t sequence_duration_at(size_t index) const {
        if (index >= sequences_.size()) {
            return 0U;
        }
        return static_cast<uint32_t>(std::min<uint64_t>(
            curated_duration(sequences_[index]),
            std::numeric_limits<uint32_t>::max()
        ));
    }

    size_t state_count() const { return states_.size(); }

    const char* state_at(size_t index) const {
        return index < states_.size() ? states_[index].id.c_str() : nullptr;
    }

    const char* current_sequence() {
        if (!loaded_) {
            return "";
        }
        const int64_t index = current_sequence_index();
        current_sequence_cache_ = index >= 0 ? sequences_[static_cast<size_t>(index)].id : "";
        return current_sequence_cache_.c_str();
    }

private:
    int fail(int result, std::string message) {
        last_result_ = result;
        last_error_ = std::move(message);
        return result;
    }

    void clear_error() {
        last_result_ = AILEN_FACE_OK;
        last_error_.clear();
    }

    bool ready() {
        if (!loaded_) {
            fail(AILEN_FACE_NOT_READY, "no FacePack is loaded");
            return false;
        }
        return true;
    }

    bool read_at(uint64_t offset, uint8_t* destination, size_t size) {
        if (size == 0) {
            return true;
        }
        if (offset > static_cast<uint64_t>(std::numeric_limits<std::streamoff>::max())) {
            return false;
        }
        stream_.clear();
        stream_.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
        if (!stream_) {
            return false;
        }
        stream_.read(reinterpret_cast<char*>(destination), static_cast<std::streamsize>(size));
        return stream_.gcount() == static_cast<std::streamsize>(size);
    }

    bool crc_range(uint64_t offset, uint64_t size, uint32_t& result) {
        std::array<uint8_t, 1024 * 1024> buffer{};
        result = 0;
        uint64_t cursor = 0;
        while (cursor < size) {
            const size_t chunk = static_cast<size_t>(std::min<uint64_t>(buffer.size(), size - cursor));
            if (!read_at(offset + cursor, buffer.data(), chunk)) {
                return false;
            }
            result = crc32_update(result, buffer.data(), chunk);
            cursor += chunk;
        }
        return true;
    }

    bool parse_header(const std::vector<uint8_t>& bytes, uint64_t actual_file_size) {
        if (!std::equal(kMagic.begin(), kMagic.end(), bytes.begin())) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack magic is invalid");
            return false;
        }
        Reader reader(bytes.data() + kMagic.size(), bytes.size() - kMagic.size());
        if (!reader.u16(header_.format_major) || !reader.u16(header_.format_minor) ||
            !reader.u16(header_.header_size) || !reader.u16(header_.required_abi) ||
            !reader.u32(header_.flags) || !reader.u32(header_.width) ||
            !reader.u32(header_.height) || !reader.u32(header_.pixel_format) ||
            !reader.u32(header_.sequence_count) || !reader.u32(header_.frame_count) ||
            !reader.u32(header_.state_count) || !reader.u32(header_.action_count) ||
            !reader.u64(header_.sequence_offset) || !reader.u64(header_.sequence_size) ||
            !reader.u64(header_.frame_offset) || !reader.u64(header_.frame_size) ||
            !reader.u64(header_.state_offset) || !reader.u64(header_.state_size) ||
            !reader.u64(header_.action_offset) || !reader.u64(header_.action_size) ||
            !reader.u64(header_.string_offset) || !reader.u64(header_.string_size) ||
            !reader.u64(header_.payload_offset) || !reader.u64(header_.payload_size) ||
            !reader.u64(header_.file_size) || !reader.u32(header_.metadata_crc) ||
            !reader.u32(header_.payload_crc) || !reader.u32(header_.pack_id_offset) ||
            !reader.u32(header_.pack_id_length) || !reader.u32(header_.pack_version_offset) ||
            !reader.u32(header_.pack_version_length)) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack header is truncated");
            return false;
        }
        if (header_.format_major != kFormatMajor || header_.format_minor > kFormatMinor ||
            header_.required_abi != AILEN_FACE_ABI_MAJOR) {
            fail(AILEN_FACE_INCOMPATIBLE, "FacePack format or ABI major is incompatible");
            return false;
        }
        if (header_.header_size != kHeaderSize || header_.file_size != actual_file_size) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack header/file size mismatch");
            return false;
        }
        if (header_.pixel_format != kPixelFormatRgb24 || header_.width == 0 ||
            header_.height == 0 || header_.width > kMaxDimension ||
            header_.height > kMaxDimension) {
            fail(AILEN_FACE_INCOMPATIBLE, "FacePack dimensions or pixel format are unsupported");
            return false;
        }
        if (header_.sequence_count == 0 || header_.sequence_count > kMaxSequences ||
            header_.frame_count > kMaxFrames || header_.state_count == 0 ||
            header_.state_count > kMaxStates || header_.action_count > kMaxActions) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack table counts exceed safety limits");
            return false;
        }
        if (header_.sequence_size != header_.sequence_count * kSequenceRecordSize ||
            header_.frame_size != header_.frame_count * kFrameRecordSize ||
            header_.state_size != header_.state_count * kStateRecordSize ||
            header_.action_size != header_.action_count * kActionRecordSize) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack table sizes are inconsistent");
            return false;
        }
        const std::array<std::pair<uint64_t, uint64_t>, 6> spans{{
            {header_.sequence_offset, header_.sequence_size},
            {header_.frame_offset, header_.frame_size},
            {header_.state_offset, header_.state_size},
            {header_.action_offset, header_.action_size},
            {header_.string_offset, header_.string_size},
            {header_.payload_offset, header_.payload_size},
        }};
        uint64_t previous_end = kHeaderSize;
        for (const auto& span : spans) {
            if (!checked_span(span.first, span.second, actual_file_size) ||
                span.first < previous_end) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack sections overlap or are out of range");
                return false;
            }
            previous_end = span.first + span.second;
        }
        if (header_.payload_offset + header_.payload_size != actual_file_size ||
            header_.payload_offset < header_.sequence_offset) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack payload boundary is invalid");
            return false;
        }
        return true;
    }

    const uint8_t* metadata_at(uint64_t absolute_offset, uint64_t size) {
        if (absolute_offset < header_.sequence_offset) {
            return nullptr;
        }
        const uint64_t relative = absolute_offset - header_.sequence_offset;
        if (relative > metadata_.size() || size > metadata_.size() - relative) {
            return nullptr;
        }
        return metadata_.data() + relative;
    }

    bool read_string(uint32_t offset, uint32_t length, std::string& result) const {
        if (length == 0 || offset > strings_.size() || length > strings_.size() - offset) {
            return false;
        }
        const char* start = reinterpret_cast<const char*>(strings_.data() + offset);
        result.assign(start, start + length);
        return result.find('\0') == std::string::npos;
    }

    bool parse_tables() {
        const uint8_t* string_data = metadata_at(header_.string_offset, header_.string_size);
        if (string_data == nullptr) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack string table is outside metadata");
            return false;
        }
        strings_.assign(string_data, string_data + header_.string_size);
        if (!read_string(header_.pack_id_offset, header_.pack_id_length, pack_id_) ||
            !read_string(header_.pack_version_offset, header_.pack_version_length, pack_version_)) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack identity strings are invalid");
            return false;
        }

        const uint8_t* sequence_data = metadata_at(header_.sequence_offset, header_.sequence_size);
        if (sequence_data == nullptr) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack sequence table is invalid");
            return false;
        }
        sequences_.reserve(header_.sequence_count);
        for (uint32_t index = 0; index < header_.sequence_count; ++index) {
            Reader reader(sequence_data + index * kSequenceRecordSize, kSequenceRecordSize);
            uint32_t id_offset = 0;
            uint32_t id_length = 0;
            uint32_t return_offset = 0;
            uint32_t return_length = 0;
            Sequence sequence{};
            if (!reader.u32(id_offset) || !reader.u32(id_length) ||
                !reader.u32(return_offset) || !reader.u32(return_length) ||
                !reader.u32(sequence.category) || !reader.u32(sequence.layer) ||
                !reader.u32(sequence.flags) || !reader.i32(sequence.priority) ||
                !reader.f32(sequence.intensity) || !reader.f32(sequence.weight) ||
                !reader.u32(sequence.fps_num) || !reader.u32(sequence.fps_den) ||
                !reader.u32(sequence.first_frame) || !reader.u32(sequence.frame_count) ||
                !reader.u32(sequence.entry) || !reader.u32(sequence.onset) ||
                !reader.u32(sequence.peak) || !reader.u32(sequence.hold_start) ||
                !reader.u32(sequence.hold_end) || !reader.u32(sequence.exit) ||
                !reader.u32(sequence.roi_x) || !reader.u32(sequence.roi_y) ||
                !reader.u32(sequence.roi_width) || !reader.u32(sequence.roi_height) ||
                !reader.u32(sequence.transition_in_ms) ||
                !reader.u32(sequence.transition_out_ms) ||
                !reader.u32(sequence.cooldown_ms) || !reader.u32(sequence.speech_style) ||
                !read_string(id_offset, id_length, sequence.id) ||
                !read_string(return_offset, return_length, sequence.return_state)) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack sequence record is malformed");
                return false;
            }
            if (find_sequence(sequence.id.c_str()) >= 0 || sequence.category < kCategoryState ||
                sequence.category > kCategorySpeech || sequence.layer < kLayerFullFrame ||
                sequence.layer > kLayerUpperFaceRoi || sequence.fps_num == 0 ||
                sequence.fps_den == 0 || sequence.frame_count == 0 ||
                sequence.first_frame > header_.frame_count ||
                sequence.frame_count > header_.frame_count - sequence.first_frame) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack sequence values are invalid");
                return false;
            }
            const bool speech_category = sequence.category == kCategorySpeech;
            const bool mouth_layer = sequence.layer == kLayerMouthRoi;
            const bool full_frame_layer = sequence.layer == kLayerFullFrame;
            const bool upper_layer = sequence.layer == kLayerUpperFaceRoi;
            const uint32_t gaze_directions = sequence.flags & kGazeDirectionMask;
            const uint32_t affect_policy = sequence.flags & kAffectPolicyMask;
            const bool expression_category =
                sequence.category == kCategoryEmotion ||
                sequence.category == kCategoryIntenseEmotion;
            if ((speech_category && !mouth_layer && !full_frame_layer) ||
                (!speech_category && mouth_layer) ||
                (speech_category && full_frame_layer && header_.format_minor < 6U) ||
                (upper_layer && sequence.category != kCategoryMicroaction) ||
                (!mouth_layer && !upper_layer && !full_frame_layer) ||
                sequence.intensity < 0.0F || sequence.intensity > 1.0F ||
                sequence.weight < 0.0F || sequence.weight > kMaxSequenceWeight ||
                sequence.speech_style > kMaxSpeechStyle ||
                (header_.format_minor == 0 && sequence.speech_style != kSpeechStyleAutomatic) ||
                (sequence.category == kCategoryMicroaction &&
                 sequence.speech_style != kSpeechStyleAutomatic) ||
                (gaze_directions != 0U &&
                 (!upper_layer || (gaze_directions & (gaze_directions - 1U)) != 0U)) ||
                ((sequence.flags & kFlagDeltaBlend) != 0U &&
                 !mouth_layer && !upper_layer) ||
                (header_.format_minor < 2 &&
                 (sequence.flags & kFlagDeltaBlend) != 0U) ||
                (header_.format_minor < 3 && affect_policy != 0U) ||
                (header_.format_minor >= 3 &&
                 ((expression_category &&
                   (affect_policy == 0U || (affect_policy & (affect_policy - 1U)) != 0U)) ||
                  (!expression_category && affect_policy != 0U)))) {
                fail(
                    AILEN_FACE_INVALID_PACK,
                    "FacePack sequence violates category/layer or numeric constraints"
                );
                return false;
            }
            const std::array<uint32_t, 6> anchors{{
                sequence.entry,
                sequence.onset,
                sequence.peak,
                sequence.hold_start,
                sequence.hold_end,
                sequence.exit,
            }};
            if (std::any_of(anchors.begin(), anchors.end(), [&](uint32_t value) {
                    return value >= sequence.frame_count;
                }) || !std::is_sorted(anchors.begin(), anchors.end())) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack sequence anchor is out of range");
                return false;
            }
            if ((sequence.layer == kLayerMouthRoi || sequence.layer == kLayerUpperFaceRoi) &&
                (sequence.roi_width == 0 || sequence.roi_height == 0 ||
                 sequence.roi_x > header_.width || sequence.roi_y > header_.height ||
                 sequence.roi_width > header_.width - sequence.roi_x ||
                 sequence.roi_height > header_.height - sequence.roi_y)) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack mouth ROI is invalid");
                return false;
            }
            sequences_.push_back(std::move(sequence));
        }

        const uint8_t* frame_data = metadata_at(header_.frame_offset, header_.frame_size);
        if (frame_data == nullptr) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack frame table is invalid");
            return false;
        }
        frames_.reserve(header_.frame_count);
        for (uint32_t index = 0; index < header_.frame_count; ++index) {
            Reader reader(frame_data + index * kFrameRecordSize, kFrameRecordSize);
            Frame frame{};
            if (!reader.u32(frame.sequence_index) || !reader.u32(frame.local_index) ||
                !reader.u32(frame.timestamp_ms) || !reader.u32(frame.encoding) ||
                !reader.u32(frame.width) || !reader.u32(frame.height) ||
                !reader.u64(frame.payload_offset) || !reader.u32(frame.payload_size) ||
                !reader.u32(frame.decoded_size) || !reader.u32(frame.crc32) ||
                !reader.u32(frame.flags) || frame.sequence_index >= sequences_.size()) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack frame record is malformed");
                return false;
            }
            const Sequence& sequence = sequences_[frame.sequence_index];
            const bool roi_layer =
                sequence.layer == kLayerMouthRoi || sequence.layer == kLayerUpperFaceRoi;
            const uint32_t expected_width = roi_layer ? sequence.roi_width : header_.width;
            const uint32_t expected_height = roi_layer ? sequence.roi_height : header_.height;
            const uint64_t expected_decoded_size =
                static_cast<uint64_t>(expected_width) * expected_height * 3U;
            const bool has_face_transform = (frame.flags & kFrameFaceTransform) != 0U;
            if (frame.encoding != 1 || frame.local_index >= sequence.frame_count ||
                index != sequence.first_frame + frame.local_index ||
                frame.width != expected_width || frame.height != expected_height ||
                expected_decoded_size > std::numeric_limits<uint32_t>::max() ||
                frame.decoded_size != expected_decoded_size || frame.payload_size == 0 ||
                (header_.format_minor < 4 && frame.flags != 0U) ||
                (roi_layer && frame.flags != 0U) ||
                (frame.flags != 0U && !has_face_transform) ||
                (frame.flags & kFrameFaceTransformReserved) != 0U ||
                (has_face_transform && decode_face_transform(frame.flags).scale <= 0.0F) ||
                frame.payload_offset < header_.payload_offset ||
                frame.payload_offset > header_.file_size ||
                frame.payload_size > header_.file_size - frame.payload_offset ||
                frame.payload_offset + frame.payload_size >
                    header_.payload_offset + header_.payload_size) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack frame values are invalid");
                return false;
            }
            frames_.push_back(frame);
        }

        const uint8_t* action_data = metadata_at(header_.action_offset, header_.action_size);
        if (action_data == nullptr && header_.action_size != 0) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack action table is invalid");
            return false;
        }
        actions_.reserve(header_.action_count);
        for (uint32_t index = 0; index < header_.action_count; ++index) {
            Reader reader(action_data + index * kActionRecordSize, kActionRecordSize);
            StateAction action{};
            if (!reader.u32(action.sequence_index) || !reader.u32(action.weight_milli) ||
                !reader.u32(action.cooldown_ms) || !reader.u32(action.flags) ||
                action.sequence_index >= sequences_.size() ||
                sequences_[action.sequence_index].category != kCategoryMicroaction) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack state-action record is invalid");
                return false;
            }
            actions_.push_back(action);
        }

        const uint8_t* state_data = metadata_at(header_.state_offset, header_.state_size);
        if (state_data == nullptr) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack state table is invalid");
            return false;
        }
        states_.reserve(header_.state_count);
        for (uint32_t index = 0; index < header_.state_count; ++index) {
            Reader reader(state_data + index * kStateRecordSize, kStateRecordSize);
            uint32_t id_offset = 0;
            uint32_t id_length = 0;
            State state{};
            uint32_t reserved = 0;
            if (!reader.u32(id_offset) || !reader.u32(id_length) ||
                !reader.u32(state.base_sequence) || !reader.u32(state.first_action) ||
                !reader.u32(state.action_count) || !reader.u32(state.wait_min_ms) ||
                !reader.u32(state.wait_max_ms) || !reader.u32(state.flags) ||
                !reader.u32(reserved) || !reader.u32(reserved) || !reader.u32(reserved) ||
                !reader.u32(reserved) || !read_string(id_offset, id_length, state.id) ||
                state.base_sequence >= sequences_.size() ||
                sequences_[state.base_sequence].category != kCategoryState ||
                state.first_action > actions_.size() ||
                state.action_count > actions_.size() - state.first_action ||
                state.wait_max_ms < state.wait_min_ms || find_state(state.id.c_str()) >= 0) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack state record is invalid");
                return false;
            }
            states_.push_back(std::move(state));
        }

        int64_t first_speech_sequence = -1;
        for (size_t index = 0; index < sequences_.size(); ++index) {
            const Sequence& sequence = sequences_[index];
            if (sequence.category == kCategoryEmotion ||
                sequence.category == kCategoryIntenseEmotion) {
                expressions_.push_back(index);
            }
            if (sequence.category == kCategorySpeech &&
                (sequence.layer == kLayerFullFrame || sequence.layer == kLayerMouthRoi)) {
                if (first_speech_sequence < 0) {
                    first_speech_sequence = static_cast<int64_t>(index);
                }
                if (default_speech_sequence_ < 0 &&
                    sequence.speech_style == kSpeechStyleNormal) {
                    default_speech_sequence_ = static_cast<int64_t>(index);
                }
            }
        }
        if (default_speech_sequence_ < 0) {
            default_speech_sequence_ = first_speech_sequence;
        }
        active_speech_sequence_ = default_speech_sequence_;
        if (states_.empty()) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack has no persistent states");
            return false;
        }
        for (const Sequence& sequence : sequences_) {
            if (find_state(sequence.return_state.c_str()) < 0) {
                fail(AILEN_FACE_INVALID_PACK, "FacePack sequence return state is unknown");
                return false;
            }
        }
        return true;
    }

    int64_t find_sequence(const char* id) const {
        if (id == nullptr) {
            return -1;
        }
        for (size_t index = 0; index < sequences_.size(); ++index) {
            if (sequences_[index].id == id) {
                return static_cast<int64_t>(index);
            }
        }
        return -1;
    }

    int64_t find_expression(const char* id) const {
        if (id == nullptr) {
            return -1;
        }
        for (const size_t index : expressions_) {
            if (sequences_[index].id == id) {
                return static_cast<int64_t>(index);
            }
        }
        return -1;
    }

    int64_t find_state(const char* id) const {
        if (id == nullptr) {
            return -1;
        }
        for (size_t index = 0; index < states_.size(); ++index) {
            if (states_[index].id == id) {
                return static_cast<int64_t>(index);
            }
        }
        return -1;
    }

    bool current_base_allows_upper_face() const {
        const int64_t index = current_sequence_index();
        return index >= 0 && static_cast<size_t>(index) < sequences_.size() &&
               (sequences_[static_cast<size_t>(index)].flags & kFlagGazeCompatible) != 0U;
    }

    int64_t find_gaze_sequence(uint32_t direction, float magnitude) const {
        int64_t selected = -1;
        float selected_distance = std::numeric_limits<float>::max();
        int32_t selected_priority = std::numeric_limits<int32_t>::min();
        for (size_t index = 0; index < sequences_.size(); ++index) {
            const Sequence& sequence = sequences_[index];
            if (sequence.category != kCategoryMicroaction ||
                sequence.layer != kLayerUpperFaceRoi ||
                (sequence.flags & direction) == 0U) {
                continue;
            }
            const float distance = std::abs(sequence.intensity - magnitude);
            if (selected < 0 || distance < selected_distance ||
                (distance == selected_distance && sequence.priority > selected_priority)) {
                selected = static_cast<int64_t>(index);
                selected_distance = distance;
                selected_priority = sequence.priority;
            }
        }
        return selected;
    }

    uint32_t desired_speech_style(float level) const {
        const int64_t base = base_sequence_index();
        if (base >= 0 && static_cast<size_t>(base) < sequences_.size()) {
            const uint32_t declared = sequences_[static_cast<size_t>(base)].speech_style;
            if (declared != kSpeechStyleAutomatic) {
                return declared;
            }
        }
        if (level < 0.24F) {
            return kSpeechStyleSoft;
        }
        if (level > 0.72F) {
            return kSpeechStyleExpressive;
        }
        return kSpeechStyleNormal;
    }

    void select_automatic_speech(float level) {
        if (speech_manual_) {
            return;
        }
        const uint32_t desired = desired_speech_style(level);
        int64_t selected = -1;
        float selected_distance = std::numeric_limits<float>::max();
        int32_t selected_priority = std::numeric_limits<int32_t>::min();
        for (size_t index = 0; index < sequences_.size(); ++index) {
            const Sequence& sequence = sequences_[index];
            if (sequence.category != kCategorySpeech ||
                (sequence.layer != kLayerFullFrame && sequence.layer != kLayerMouthRoi) ||
                sequence.speech_style != desired) {
                continue;
            }
            const float distance = std::abs(sequence.intensity - level);
            if (selected < 0 || distance < selected_distance ||
                (distance == selected_distance && sequence.priority > selected_priority)) {
                selected = static_cast<int64_t>(index);
                selected_distance = distance;
                selected_priority = sequence.priority;
            }
        }
        if (selected < 0) {
            selected = default_speech_sequence_;
        }
        if (selected != active_speech_sequence_) {
            active_speech_sequence_ = selected;
            speech_elapsed_ms_ = 0;
            last_speech_frame_ = -1;
        }
    }

    uint64_t next_random() {
        uint64_t value = rng_state_;
        value ^= value >> 12U;
        value ^= value << 25U;
        value ^= value >> 27U;
        rng_state_ = value;
        return value * 2685821657736338717ULL;
    }

    uint32_t random_between(uint32_t low, uint32_t high) {
        if (high <= low) {
            return low;
        }
        return low + static_cast<uint32_t>(next_random() % (static_cast<uint64_t>(high - low) + 1U));
    }

    void schedule_next_action() {
        if (current_state_ < 0 || static_cast<size_t>(current_state_) >= states_.size()) {
            next_action_at_ms_ = std::numeric_limits<uint64_t>::max();
            return;
        }
        const State& state = states_[static_cast<size_t>(current_state_)];
        next_action_at_ms_ = total_ms_ + random_between(state.wait_min_ms, state.wait_max_ms);
    }

    void choose_state_action() {
        if (current_state_ < 0 || static_cast<size_t>(current_state_) >= states_.size()) {
            schedule_next_action();
            return;
        }
        const State& state = states_[static_cast<size_t>(current_state_)];
        struct WeightedAction {
            const StateAction* action;
            uint64_t weight;
        };
        uint64_t total_weight = 0;
        std::vector<WeightedAction> eligible;
        for (uint32_t offset = 0; offset < state.action_count; ++offset) {
            const StateAction& action = actions_[state.first_action + offset];
            const Sequence& sequence = sequences_[action.sequence_index];
            if (sequence.layer == kLayerFullFrame && active_expression_ >= 0) {
                continue;
            }
            if (sequence.layer == kLayerUpperFaceRoi && !current_base_allows_upper_face()) {
                continue;
            }
            const uint32_t cooldown = std::max(
                action.cooldown_ms,
                sequence.cooldown_ms
            );
            if (has_triggered_[action.sequence_index] &&
                total_ms_ - last_trigger_ms_[action.sequence_index] < cooldown) {
                continue;
            }
            const uint64_t effective_weight = static_cast<uint64_t>(std::llround(
                static_cast<double>(action.weight_milli) * sequence.weight
            ));
            if (effective_weight == 0 ||
                effective_weight > std::numeric_limits<uint64_t>::max() - total_weight) {
                continue;
            }
            eligible.push_back(WeightedAction{&action, effective_weight});
            total_weight += effective_weight;
        }
        if (eligible.empty() || total_weight == 0) {
            schedule_next_action();
            return;
        }
        uint64_t draw = next_random() % total_weight;
        const WeightedAction* selected = &eligible.back();
        for (const WeightedAction& candidate : eligible) {
            if (draw < candidate.weight) {
                selected = &candidate;
                break;
            }
            draw -= candidate.weight;
        }
        const uint32_t selected_index = selected->action->sequence_index;
        if (sequences_[selected_index].layer == kLayerUpperFaceRoi) {
            active_upper_action_ = static_cast<int64_t>(selected_index);
            upper_elapsed_ms_ = 0;
            upper_is_explicit_gaze_ = false;
        } else {
            active_action_ = static_cast<int64_t>(selected_index);
            action_elapsed_ms_ = 0;
        }
        has_triggered_[selected_index] = true;
        last_trigger_ms_[selected_index] = total_ms_;
        next_action_at_ms_ = std::numeric_limits<uint64_t>::max();
    }

    uint64_t natural_duration(const Sequence& sequence) const {
        const uint64_t numerator =
            static_cast<uint64_t>(sequence.frame_count) * 1000ULL * sequence.fps_den;
        return std::max<uint64_t>(1, (numerator + sequence.fps_num - 1U) / sequence.fps_num);
    }

    uint64_t frame_range_duration(
        const Sequence& sequence,
        uint32_t first,
        uint32_t last
    ) const {
        const uint64_t count = last >= first ? static_cast<uint64_t>(last - first) + 1U : 1U;
        const uint64_t numerator = count * 1000ULL * sequence.fps_den;
        return std::max<uint64_t>(1, (numerator + sequence.fps_num - 1U) / sequence.fps_num);
    }

    uint64_t curated_duration(const Sequence& sequence) const {
        if (sequence.transition_in_ms == 0 && sequence.transition_out_ms == 0) {
            return natural_duration(sequence);
        }
        const uint64_t transition_in = sequence.transition_in_ms != 0
            ? sequence.transition_in_ms
            : frame_range_duration(sequence, sequence.entry, sequence.hold_start);
        const uint64_t hold =
            frame_range_duration(sequence, sequence.hold_start, sequence.hold_end);
        const uint64_t transition_out = sequence.transition_out_ms != 0
            ? sequence.transition_out_ms
            : frame_range_duration(sequence, sequence.hold_end, sequence.exit);
        return transition_in + hold + transition_out;
    }

    uint64_t playback_duration(const Sequence& sequence, bool expression) const {
        const uint64_t curated = curated_duration(sequence);
        return expression ? std::max<uint64_t>(curated, expression_minimum_ms_) : curated;
    }

    static uint32_t map_phase(
        uint32_t first,
        uint32_t last,
        uint64_t elapsed,
        uint64_t duration
    ) {
        if (last <= first || duration <= 1) {
            return last;
        }
        const uint64_t bounded = std::min(elapsed, duration - 1U);
        return first + static_cast<uint32_t>(
            static_cast<uint64_t>(last - first) * bounded / (duration - 1U)
        );
    }

    uint32_t local_frame_for(const Sequence& sequence, uint64_t elapsed_ms, bool expression) const {
        const uint64_t natural = natural_duration(sequence);
        uint64_t mapped = elapsed_ms;
        if (sequence.transition_in_ms != 0 || sequence.transition_out_ms != 0) {
            const uint64_t transition_in = sequence.transition_in_ms != 0
                ? sequence.transition_in_ms
                : frame_range_duration(sequence, sequence.entry, sequence.hold_start);
            const uint64_t natural_hold =
                frame_range_duration(sequence, sequence.hold_start, sequence.hold_end);
            const uint64_t transition_out = sequence.transition_out_ms != 0
                ? sequence.transition_out_ms
                : frame_range_duration(sequence, sequence.hold_end, sequence.exit);
            const uint64_t curated = transition_in + natural_hold + transition_out;
            const uint64_t extra_hold = expression && expression_minimum_ms_ > curated
                ? expression_minimum_ms_ - curated
                : 0;
            if (mapped < transition_in) {
                return apply_intensity(
                    sequence,
                    map_phase(sequence.entry, sequence.hold_start, mapped, transition_in),
                    expression
                );
            }
            mapped -= transition_in;
            const uint64_t hold_duration = natural_hold + extra_hold;
            if (mapped < hold_duration) {
                const uint32_t hold_count = sequence.hold_end >= sequence.hold_start
                    ? sequence.hold_end - sequence.hold_start + 1U
                    : 1U;
                const uint64_t hold_frame =
                    mapped * sequence.fps_num /
                    (1000ULL * static_cast<uint64_t>(sequence.fps_den));
                return apply_intensity(
                    sequence,
                    sequence.hold_start + static_cast<uint32_t>(hold_frame % hold_count),
                    expression
                );
            }
            mapped -= hold_duration;
            return apply_intensity(
                sequence,
                map_phase(sequence.hold_end, sequence.exit, mapped, transition_out),
                expression
            );
        }
        if (expression && expression_minimum_ms_ > natural) {
            const uint64_t extra = expression_minimum_ms_ - natural;
            const uint64_t frame_ms_num = 1000ULL * sequence.fps_den;
            const uint64_t hold_begin =
                static_cast<uint64_t>(sequence.hold_end + 1U) * frame_ms_num / sequence.fps_num;
            if (mapped >= hold_begin && mapped < hold_begin + extra) {
                const uint32_t hold_count = sequence.hold_end >= sequence.hold_start
                    ? sequence.hold_end - sequence.hold_start + 1U
                    : 1U;
                const uint64_t hold_frame =
                    (mapped - hold_begin) * sequence.fps_num / frame_ms_num;
                return apply_intensity(
                    sequence,
                    sequence.hold_start + static_cast<uint32_t>(hold_frame % hold_count),
                    expression
                );
            }
            if (mapped >= hold_begin + extra) {
                mapped -= extra;
            }
        }
        if ((sequence.flags & kFlagLoopable) != 0U && natural > 0) {
            mapped %= natural;
        }
        const uint64_t index = mapped * sequence.fps_num /
                               (1000ULL * static_cast<uint64_t>(sequence.fps_den));
        return apply_intensity(
            sequence,
            static_cast<uint32_t>(std::min<uint64_t>(sequence.frame_count - 1U, index)),
            expression
        );
    }

    uint32_t apply_intensity(
        const Sequence& sequence,
        uint32_t frame_index,
        bool expression
    ) const {
        if (!expression || !has_intensity_override_ || sequence.peak <= sequence.onset) {
            return frame_index;
        }
        const float intrinsic = std::max(0.05F, sequence.intensity);
        const float ratio = std::clamp(intensity_ / intrinsic, 0.0F, 1.0F);
        const uint32_t mild_peak = sequence.onset + static_cast<uint32_t>(std::lround(
            static_cast<float>(sequence.peak - sequence.onset) * ratio
        ));
        if (frame_index < sequence.onset) {
            return frame_index;
        }
        if (frame_index <= sequence.peak) {
            const uint32_t progress = frame_index - sequence.onset;
            return sequence.onset + static_cast<uint32_t>(
                static_cast<uint64_t>(progress) * (mild_peak - sequence.onset) /
                (sequence.peak - sequence.onset)
            );
        }
        if (frame_index <= sequence.hold_end) {
            return mild_peak;
        }
        if (sequence.exit <= sequence.hold_end) {
            return frame_index;
        }
        const uint32_t exit_progress = std::min(frame_index, sequence.exit) - sequence.hold_end;
        return mild_peak + static_cast<uint32_t>(
            static_cast<uint64_t>(exit_progress) * (sequence.exit - mild_peak) /
            (sequence.exit - sequence.hold_end)
        );
    }

    int64_t base_sequence_index() const {
        if (active_expression_ >= 0) {
            return active_expression_;
        }
        if (active_action_ >= 0) {
            return active_action_;
        }
        if (current_state_ >= 0 && static_cast<size_t>(current_state_) < states_.size()) {
            return states_[static_cast<size_t>(current_state_)].base_sequence;
        }
        return -1;
    }

    int64_t current_sequence_index() const {
        const int64_t base = base_sequence_index();
        if (speech_level_ > 0.0F && active_speech_sequence_ >= 0 && base >= 0 &&
            static_cast<size_t>(active_speech_sequence_) < sequences_.size() &&
            static_cast<size_t>(base) < sequences_.size()) {
            const Sequence& speech =
                sequences_[static_cast<size_t>(active_speech_sequence_)];
            if (speech.category == kCategorySpeech && speech.layer == kLayerFullFrame &&
                (sequences_[static_cast<size_t>(base)].flags & kFlagSpeechCompatible) != 0U) {
                return active_speech_sequence_;
            }
        }
        return base;
    }

    bool decode_frame(uint32_t frame_index, std::vector<uint8_t>& destination) {
        if (frame_index >= frames_.size()) {
            fail(AILEN_FACE_INVALID_PACK, "requested frame is outside the frame table");
            return false;
        }
        const Frame& frame = frames_[frame_index];
        std::vector<uint8_t> encoded(frame.payload_size);
        if (!read_at(frame.payload_offset, encoded.data(), encoded.size())) {
            fail(AILEN_FACE_IO_ERROR, "could not read a FacePack frame payload");
            return false;
        }
        if (crc32_update(0, encoded.data(), encoded.size()) != frame.crc32) {
            fail(AILEN_FACE_INVALID_PACK, "FacePack frame checksum does not match");
            return false;
        }
        std::string decode_error;
        if (!decode_jpeg(encoded, frame.width, frame.height, destination, decode_error)) {
            fail(AILEN_FACE_DECODE_ERROR, std::move(decode_error));
            return false;
        }
        return true;
    }

    bool composite_roi(
        const Sequence& sequence,
        const Frame& base_frame,
        uint64_t elapsed_ms,
        float strength,
        std::vector<uint8_t>& cache,
        int64_t& cached_frame,
        int64_t& rendered_frame
    ) {
        if (sequence.layer != kLayerMouthRoi && sequence.layer != kLayerUpperFaceRoi) {
            fail(AILEN_FACE_INVALID_PACK, "active overlay is not an ROI layer");
            return false;
        }
        const uint32_t local = local_frame_for(sequence, elapsed_ms, false);
        const uint32_t frame_index = sequence.first_frame + local;
        rendered_frame = frame_index;
        if (cached_frame != static_cast<int64_t>(frame_index)) {
            if (!decode_frame(frame_index, cache)) {
                return false;
            }
            const uint64_t expected =
                static_cast<uint64_t>(sequence.roi_width) * sequence.roi_height * 3U;
            if (cache.size() != expected) {
                fail(AILEN_FACE_DECODE_ERROR, "ROI JPEG decoded to an unexpected size");
                return false;
            }
            cached_frame = frame_index;
        }
        const bool delta_blend = (sequence.flags & kFlagDeltaBlend) != 0U;
        const uint32_t minimum_roi_dimension =
            std::min(sequence.roi_width, sequence.roi_height);
        // A replacement ROI carries source skin/light as well as the feature.
        // Fade it across the full short axis so the source rectangle never has
        // an opaque edge. Centered delta layers contain no foreign skin and can
        // use the narrower feather without attenuating their intended change.
        const bool soft_replacement_mask =
            header_.format_minor >= 5U && !delta_blend;
        const uint32_t feather = soft_replacement_mask
            ? std::max<uint32_t>(2U, (minimum_roi_dimension + 1U) / 2U)
            : std::max<uint32_t>(4U, minimum_roi_dimension / 10U);
        const float bounded_strength = std::clamp(strength, 0.0F, 1.0F);
        const FaceTransform placement = decode_face_transform(base_frame.flags);
        const float cosine = std::cos(placement.angle_radians);
        const float sine = std::sin(placement.angle_radians);
        const float transform_a = placement.scale * cosine;
        const float transform_b = -placement.scale * sine;
        const float transform_c = placement.scale * sine;
        const float transform_d = placement.scale * cosine;
        const bool identity =
            std::abs(placement.translate_x) < 0.01F &&
            std::abs(placement.translate_y) < 0.01F &&
            std::abs(placement.angle_radians) < 0.0001F &&
            std::abs(placement.scale - 1.0F) < 0.0001F;
        if (identity) {
            for (uint32_t y = 0; y < sequence.roi_height; ++y) {
                for (uint32_t x = 0; x < sequence.roi_width; ++x) {
                    const uint32_t edge = std::min({
                        x,
                        y,
                        sequence.roi_width - 1U - x,
                        sequence.roi_height - 1U - y,
                    });
                    float alpha = std::min(1.0F, static_cast<float>(edge) / feather);
                    alpha = alpha * alpha * (3.0F - 2.0F * alpha) * bounded_strength;
                    const size_t source =
                        (static_cast<size_t>(y) * sequence.roi_width + x) * 3U;
                    const size_t destination =
                        (static_cast<size_t>(sequence.roi_y + y) * header_.width +
                         sequence.roi_x + x) * 3U;
                    for (size_t channel = 0; channel < 3; ++channel) {
                        const float base = output_[destination + channel];
                        const float overlay = cache[source + channel];
                        const float blended = delta_blend
                            ? base + (overlay - 128.0F) * alpha
                            : base + (overlay - base) * alpha;
                        output_[destination + channel] = static_cast<uint8_t>(
                            std::clamp(blended, 0.0F, 255.0F)
                        );
                    }
                }
            }
            return true;
        }

        auto transform_point = [&](float x, float y) {
            return std::array<float, 2>{
                transform_a * x + transform_b * y + placement.translate_x,
                transform_c * x + transform_d * y + placement.translate_y,
            };
        };
        const float left = static_cast<float>(sequence.roi_x);
        const float top = static_cast<float>(sequence.roi_y);
        const float right = left + static_cast<float>(sequence.roi_width - 1U);
        const float bottom = top + static_cast<float>(sequence.roi_height - 1U);
        const std::array<std::array<float, 2>, 4> corners{{
            transform_point(left, top),
            transform_point(right, top),
            transform_point(left, bottom),
            transform_point(right, bottom),
        }};
        float minimum_x = corners[0][0];
        float maximum_x = corners[0][0];
        float minimum_y = corners[0][1];
        float maximum_y = corners[0][1];
        for (const auto& corner : corners) {
            minimum_x = std::min(minimum_x, corner[0]);
            maximum_x = std::max(maximum_x, corner[0]);
            minimum_y = std::min(minimum_y, corner[1]);
            maximum_y = std::max(maximum_y, corner[1]);
        }
        const int32_t destination_left = std::max<int32_t>(
            0,
            static_cast<int32_t>(std::floor(minimum_x))
        );
        const int32_t destination_right = std::min<int32_t>(
            static_cast<int32_t>(header_.width) - 1,
            static_cast<int32_t>(std::ceil(maximum_x))
        );
        const int32_t destination_top = std::max<int32_t>(
            0,
            static_cast<int32_t>(std::floor(minimum_y))
        );
        const int32_t destination_bottom = std::min<int32_t>(
            static_cast<int32_t>(header_.height) - 1,
            static_cast<int32_t>(std::ceil(maximum_y))
        );
        const float determinant = transform_a * transform_d - transform_b * transform_c;
        if (std::abs(determinant) < 1e-6F) {
            fail(AILEN_FACE_INVALID_PACK, "frame face placement transform is singular");
            return false;
        }
        for (int32_t destination_y = destination_top;
             destination_y <= destination_bottom;
             ++destination_y) {
            for (int32_t destination_x = destination_left;
                 destination_x <= destination_right;
                 ++destination_x) {
                const float shifted_x =
                    static_cast<float>(destination_x) - placement.translate_x;
                const float shifted_y =
                    static_cast<float>(destination_y) - placement.translate_y;
                const float canonical_x =
                    (transform_d * shifted_x - transform_b * shifted_y) / determinant;
                const float canonical_y =
                    (-transform_c * shifted_x + transform_a * shifted_y) / determinant;
                const float source_x = canonical_x - left;
                const float source_y = canonical_y - top;
                if (source_x < 0.0F || source_y < 0.0F ||
                    source_x > static_cast<float>(sequence.roi_width - 1U) ||
                    source_y > static_cast<float>(sequence.roi_height - 1U)) {
                    continue;
                }
                const float edge = std::min({
                    source_x,
                    source_y,
                    static_cast<float>(sequence.roi_width - 1U) - source_x,
                    static_cast<float>(sequence.roi_height - 1U) - source_y,
                });
                float alpha = std::min(1.0F, edge / static_cast<float>(feather));
                alpha = alpha * alpha * (3.0F - 2.0F * alpha) * bounded_strength;
                const uint32_t x0 = static_cast<uint32_t>(std::floor(source_x));
                const uint32_t y0 = static_cast<uint32_t>(std::floor(source_y));
                const uint32_t x1 = std::min(x0 + 1U, sequence.roi_width - 1U);
                const uint32_t y1 = std::min(y0 + 1U, sequence.roi_height - 1U);
                const float weight_x = source_x - static_cast<float>(x0);
                const float weight_y = source_y - static_cast<float>(y0);
                const size_t destination =
                    (static_cast<size_t>(destination_y) * header_.width +
                     static_cast<uint32_t>(destination_x)) * 3U;
                for (size_t channel = 0; channel < 3; ++channel) {
                    const auto sample = [&](uint32_t x, uint32_t y) {
                        return static_cast<float>(
                            cache[(static_cast<size_t>(y) * sequence.roi_width + x) * 3U + channel]
                        );
                    };
                    const float top_value =
                        sample(x0, y0) + (sample(x1, y0) - sample(x0, y0)) * weight_x;
                    const float bottom_value =
                        sample(x0, y1) + (sample(x1, y1) - sample(x0, y1)) * weight_x;
                    const float overlay = top_value + (bottom_value - top_value) * weight_y;
                    const float base = output_[destination + channel];
                    const float blended = delta_blend
                        ? base + (overlay - 128.0F) * alpha
                        : base + (overlay - base) * alpha;
                    output_[destination + channel] = static_cast<uint8_t>(
                        std::clamp(blended, 0.0F, 255.0F)
                    );
                }
            }
        }
        return true;
    }

    bool render_current() {
        const int64_t sequence_index = current_sequence_index();
        if (sequence_index < 0 || static_cast<size_t>(sequence_index) >= sequences_.size()) {
            fail(AILEN_FACE_NOT_READY, "FacePack has no renderable current sequence");
            return false;
        }
        const Sequence& sequence = sequences_[static_cast<size_t>(sequence_index)];
        if (sequence.layer != kLayerFullFrame) {
            fail(AILEN_FACE_INVALID_PACK, "current base sequence is not full-frame");
            return false;
        }
        uint64_t elapsed = state_elapsed_ms_;
        bool expression = false;
        const bool full_frame_speech =
            speech_level_ > 0.0F && active_speech_sequence_ == sequence_index &&
            sequence.category == kCategorySpeech && sequence.layer == kLayerFullFrame;
        if (full_frame_speech) {
            elapsed = speech_elapsed_ms_;
        } else if (active_expression_ >= 0) {
            elapsed = expression_elapsed_ms_;
            expression = true;
        } else if (active_action_ >= 0) {
            elapsed = action_elapsed_ms_;
        }
        const uint32_t local_index = local_frame_for(sequence, elapsed, expression);
        const uint32_t frame_index = sequence.first_frame + local_index;
        if (last_base_frame_ != static_cast<int64_t>(frame_index)) {
            if (!decode_frame(frame_index, base_cache_)) {
                return false;
            }
            if (base_cache_.size() != output_.size()) {
                fail(AILEN_FACE_DECODE_ERROR, "full-frame JPEG decoded to an unexpected size");
                return false;
            }
            last_base_frame_ = frame_index;
        }
        output_ = base_cache_;

        int64_t rendered_upper_frame = -1;
        if (active_upper_action_ >= 0 &&
            (sequence.flags & kFlagGazeCompatible) != 0U) {
            const Sequence& upper = sequences_[static_cast<size_t>(active_upper_action_)];
            if (upper.category != kCategoryMicroaction || upper.layer != kLayerUpperFaceRoi) {
                fail(AILEN_FACE_INVALID_PACK, "active upper-face action is not composable");
                return false;
            }
            if (!composite_roi(
                    upper,
                    frames_[frame_index],
                    upper_elapsed_ms_,
                    1.0F,
                    upper_cache_,
                    last_upper_frame_,
                    rendered_upper_frame
                )) {
                return false;
            }
        }

        int64_t rendered_speech_frame = -1;
        int rendered_speech_strength = 0;
        if (full_frame_speech) {
            record_render_signature(
                frame_index,
                rendered_upper_frame,
                rendered_speech_frame,
                rendered_speech_strength
            );
            return true;
        }
        if (speech_level_ <= 0.0F || active_speech_sequence_ < 0 ||
            (sequence.flags & kFlagSpeechCompatible) == 0U) {
            record_render_signature(
                frame_index,
                rendered_upper_frame,
                rendered_speech_frame,
                rendered_speech_strength
            );
            return true;
        }
        const Sequence& speech = sequences_[static_cast<size_t>(active_speech_sequence_)];
        if (speech.category != kCategorySpeech || speech.layer != kLayerMouthRoi) {
            fail(AILEN_FACE_INVALID_PACK, "active speech sequence is not a mouth layer");
            return false;
        }
        rendered_speech_strength = static_cast<int>(std::lround(speech_level_ * 255.0F));
        float speech_strength = std::sqrt(speech_level_);
        if ((speech.flags & kFlagDeltaBlend) != 0U) {
            speech_strength *= 0.70F;
        }
        if (!composite_roi(
                speech,
                frames_[frame_index],
                speech_elapsed_ms_,
                speech_strength,
                speech_cache_,
                last_speech_frame_,
                rendered_speech_frame
            )) {
            return false;
        }
        record_render_signature(
            frame_index,
            rendered_upper_frame,
            rendered_speech_frame,
            rendered_speech_strength
        );
        return true;
    }

    void record_render_signature(
        uint32_t base_frame,
        int64_t upper_frame,
        int64_t speech_frame,
        int speech_strength
    ) {
        if (last_render_base_frame_ != static_cast<int64_t>(base_frame) ||
            last_render_upper_frame_ != upper_frame ||
            last_render_speech_frame_ != speech_frame ||
            last_render_speech_strength_ != speech_strength) {
            ++frame_generation_;
            last_render_base_frame_ = base_frame;
            last_render_upper_frame_ = upper_frame;
            last_render_speech_frame_ = speech_frame;
            last_render_speech_strength_ = speech_strength;
        }
    }

    std::ifstream stream_;
    Header header_{};
    std::vector<uint8_t> metadata_;
    std::vector<uint8_t> strings_;
    std::vector<Sequence> sequences_;
    std::vector<Frame> frames_;
    std::vector<State> states_;
    std::vector<StateAction> actions_;
    std::vector<size_t> expressions_;
    std::string pack_id_;
    std::string pack_version_;
    std::vector<uint8_t> output_;
    std::vector<uint8_t> base_cache_;
    std::vector<uint8_t> upper_cache_;
    std::vector<uint8_t> speech_cache_;
    std::vector<uint64_t> last_trigger_ms_;
    std::vector<bool> has_triggered_;
    int64_t last_base_frame_{-1};
    int64_t last_upper_frame_{-1};
    int64_t last_speech_frame_{-1};
    int64_t last_render_base_frame_{-1};
    int64_t last_render_upper_frame_{-1};
    int64_t last_render_speech_frame_{-1};
    int last_render_speech_strength_{-1};
    uint64_t frame_generation_{};
    int64_t current_state_{-1};
    int64_t active_expression_{-1};
    int64_t active_action_{-1};
    int64_t active_upper_action_{-1};
    int64_t default_speech_sequence_{-1};
    int64_t active_speech_sequence_{-1};
    uint64_t total_ms_{};
    uint64_t state_elapsed_ms_{};
    uint64_t expression_elapsed_ms_{};
    uint64_t action_elapsed_ms_{};
    uint64_t upper_elapsed_ms_{};
    uint64_t speech_elapsed_ms_{};
    uint64_t next_action_at_ms_{};
    uint32_t expression_minimum_ms_{};
    uint64_t rng_state_{0xA11E5EED5EED1234ULL};
    float intensity_{1.0F};
    float speech_level_{};
    float gaze_x_{};
    float gaze_y_{};
    bool loaded_{};
    bool has_intensity_override_{};
    bool speech_manual_{};
    bool upper_is_explicit_gaze_{};
    int last_result_{AILEN_FACE_NOT_READY};
    std::string last_error_;
    std::string current_sequence_cache_;
};

}  // namespace

struct ailen_face_handle {
    std::mutex mutex;
    Engine engine;
    std::array<char, 512> abi_error{};

    void clear_abi_error() noexcept {
        abi_error[0] = '\0';
    }

    void set_abi_error(const char* message) noexcept {
        const char* source = message != nullptr ? message : "unknown native exception";
        size_t length = 0;
        while (source[length] != '\0' && length + 1U < abi_error.size()) {
            ++length;
        }
        std::memcpy(abi_error.data(), source, length);
        abi_error[length] = '\0';
    }
};

namespace {

template <typename Function>
int guard_result(ailen_face_handle* handle, Function&& function) noexcept {
    if (handle == nullptr) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        handle->clear_abi_error();
        return function(handle->engine);
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception in native face engine");
    }
    return AILEN_FACE_INTERNAL_ERROR;
}

template <typename Value, typename Function>
Value guard_value(
    ailen_face_handle* handle,
    Value fallback,
    Function&& function
) noexcept {
    if (handle == nullptr) {
        return fallback;
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        handle->clear_abi_error();
        return function(handle->engine);
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception in native face engine");
    }
    return fallback;
}

template <typename Function>
void guard_void(ailen_face_handle* handle, Function&& function) noexcept {
    if (handle == nullptr) {
        return;
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        handle->clear_abi_error();
        function(handle->engine);
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception in native face engine");
    }
}

template <typename Function>
const char* guard_text(ailen_face_handle* handle, Function&& function) noexcept {
    if (handle == nullptr) {
        return copy_abi_text("");
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        handle->clear_abi_error();
        return copy_abi_text(function(handle->engine));
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception in native face engine");
    }
    return copy_abi_text("");
}

}  // namespace

extern "C" {

uint32_t ailen_face_get_abi_version(void) noexcept {
    return AILEN_FACE_ABI_VERSION;
}

ailen_face_handle* ailen_face_create(void) noexcept {
    try {
        return new ailen_face_handle();
    } catch (...) {
        return nullptr;
    }
}

void ailen_face_destroy(ailen_face_handle* handle) noexcept {
    try {
        delete handle;
    } catch (...) {
        // Destruction cannot report through a dead handle, but no exception may cross the C ABI.
    }
}

int ailen_face_load_pack(ailen_face_handle* handle, const char* path_utf8) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.load(path_utf8); });
}

void ailen_face_unload_pack(ailen_face_handle* handle) noexcept {
    guard_void(handle, [](Engine& engine) { engine.unload_locked(); });
}

const char* ailen_face_get_pack_id(ailen_face_handle* handle) noexcept {
    return guard_text(handle, [](Engine& engine) { return engine.pack_id().c_str(); });
}

const char* ailen_face_get_pack_version(ailen_face_handle* handle) noexcept {
    return guard_text(handle, [](Engine& engine) { return engine.pack_version().c_str(); });
}

size_t ailen_face_get_expression_count(ailen_face_handle* handle) noexcept {
    return guard_value<size_t>(
        handle, 0, [](Engine& engine) { return engine.expression_count(); }
    );
}

const char* ailen_face_get_expression(ailen_face_handle* handle, size_t index) noexcept {
    return guard_text(handle, [&](Engine& engine) { return engine.expression_at(index); });
}

int ailen_face_has_expression(ailen_face_handle* handle, const char* expression) noexcept {
    return guard_value<int>(
        handle, 0, [&](Engine& engine) { return engine.has_expression(expression); }
    );
}

size_t ailen_face_get_sequence_count(ailen_face_handle* handle) noexcept {
    return guard_value<size_t>(
        handle, 0, [](Engine& engine) { return engine.sequence_count(); }
    );
}

const char* ailen_face_get_sequence(ailen_face_handle* handle, size_t index) noexcept {
    return guard_text(handle, [&](Engine& engine) { return engine.sequence_at(index); });
}

uint32_t ailen_face_get_sequence_category(ailen_face_handle* handle, size_t index) noexcept {
    return guard_value<uint32_t>(
        handle, 0, [&](Engine& engine) { return engine.sequence_category_at(index); }
    );
}

uint32_t ailen_face_get_sequence_layer(ailen_face_handle* handle, size_t index) noexcept {
    return guard_value<uint32_t>(
        handle, 0, [&](Engine& engine) { return engine.sequence_layer_at(index); }
    );
}

uint32_t ailen_face_get_sequence_flags(ailen_face_handle* handle, size_t index) noexcept {
    return guard_value<uint32_t>(
        handle, 0, [&](Engine& engine) { return engine.sequence_flags_at(index); }
    );
}

uint32_t ailen_face_get_sequence_duration_ms(ailen_face_handle* handle, size_t index) noexcept {
    return guard_value<uint32_t>(
        handle, 0, [&](Engine& engine) { return engine.sequence_duration_at(index); }
    );
}

size_t ailen_face_get_state_count(ailen_face_handle* handle) noexcept {
    return guard_value<size_t>(handle, 0, [](Engine& engine) { return engine.state_count(); });
}

const char* ailen_face_get_state(ailen_face_handle* handle, size_t index) noexcept {
    return guard_text(handle, [&](Engine& engine) { return engine.state_at(index); });
}

int ailen_face_set_state(ailen_face_handle* handle, const char* state) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.set_state(state); });
}

int ailen_face_trigger_expression(
    ailen_face_handle* handle,
    const char* expression,
    uint32_t minimum_duration_ms
) noexcept {
    return guard_result(handle, [&](Engine& engine) {
        return engine.trigger_expression(expression, minimum_duration_ms);
    });
}

int ailen_face_clear_expression(ailen_face_handle* handle) noexcept {
    return guard_result(handle, [](Engine& engine) { return engine.clear_expression(); });
}

int ailen_face_trigger_microaction(
    ailen_face_handle* handle,
    const char* microaction
) noexcept {
    return guard_result(handle, [&](Engine& engine) {
        return engine.trigger_microaction(microaction);
    });
}

int ailen_face_set_intensity(ailen_face_handle* handle, float intensity) noexcept {
    return guard_result(
        handle, [&](Engine& engine) { return engine.set_intensity(intensity); }
    );
}

int ailen_face_set_speech_level(ailen_face_handle* handle, float level) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.set_speech(level); });
}

int ailen_face_set_viseme(ailen_face_handle* handle, const char* viseme) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.set_viseme(viseme); });
}

int ailen_face_set_gaze(ailen_face_handle* handle, float x, float y) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.set_gaze(x, y); });
}

int ailen_face_set_random_seed(ailen_face_handle* handle, uint64_t seed) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.set_seed(seed); });
}

int ailen_face_update(ailen_face_handle* handle, uint32_t delta_ms) noexcept {
    return guard_result(handle, [&](Engine& engine) { return engine.update(delta_ms); });
}

const uint8_t* ailen_face_get_frame(ailen_face_handle* handle) noexcept {
    if (handle == nullptr) {
        return nullptr;
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        handle->clear_abi_error();
        abi_frame_snapshot = handle->engine.output();
        return abi_frame_snapshot.empty() ? nullptr : abi_frame_snapshot.data();
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception while copying legacy frame snapshot");
    }
    abi_frame_snapshot.clear();
    return nullptr;
}

size_t ailen_face_get_frame_size(ailen_face_handle* handle) noexcept {
    return guard_value<size_t>(handle, 0, [](Engine& engine) { return engine.output().size(); });
}

int ailen_face_copy_frame(
    ailen_face_handle* handle,
    uint8_t* destination,
    size_t destination_size
) noexcept {
    if (destination == nullptr) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    return guard_result(handle, [&](Engine& engine) {
        const auto& output = engine.output();
        if (output.empty()) {
            return AILEN_FACE_NOT_READY;
        }
        if (destination_size < output.size()) {
            return AILEN_FACE_INVALID_ARGUMENT;
        }
        std::memcpy(destination, output.data(), output.size());
        return AILEN_FACE_OK;
    });
}

int ailen_face_copy_frame_scaled(
    ailen_face_handle* handle,
    uint8_t* destination,
    size_t destination_size,
    uint32_t destination_width,
    uint32_t destination_height,
    size_t destination_stride
) noexcept {
    if (destination == nullptr || destination_width == 0U || destination_height == 0U ||
        destination_width > kMaxDimension || destination_height > kMaxDimension) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    const size_t row_bytes = static_cast<size_t>(destination_width) * 3U;
    if (destination_stride < row_bytes) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    const size_t rows_before_last = static_cast<size_t>(destination_height - 1U);
    if (rows_before_last != 0U &&
        destination_stride > (std::numeric_limits<size_t>::max() - row_bytes) /
                                 rows_before_last) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    const size_t required_size = rows_before_last * destination_stride + row_bytes;
    if (destination_size < required_size) {
        return AILEN_FACE_INVALID_ARGUMENT;
    }
    return guard_result(handle, [&](Engine& engine) {
        const auto& source = engine.output();
        const uint32_t source_width = engine.width();
        const uint32_t source_height = engine.height();
        const size_t expected_source_size =
            static_cast<size_t>(source_width) * source_height * 3U;
        if (source.empty() || source.size() != expected_source_size) {
            return AILEN_FACE_NOT_READY;
        }
        if (source_width == destination_width && source_height == destination_height) {
            for (uint32_t y = 0; y < source_height; ++y) {
                std::memcpy(
                    destination + static_cast<size_t>(y) * destination_stride,
                    source.data() + static_cast<size_t>(y) * row_bytes,
                    row_bytes
                );
            }
            return AILEN_FACE_OK;
        }

        std::vector<uint32_t> x0(destination_width);
        std::vector<uint32_t> x1(destination_width);
        std::vector<uint32_t> x_weight(destination_width);
        for (uint32_t x = 0; x < destination_width; ++x) {
            int64_t source_fixed =
                (static_cast<int64_t>(2U * x + 1U) * source_width * 128LL) /
                    destination_width -
                128LL;
            source_fixed = std::clamp<int64_t>(
                source_fixed,
                0,
                static_cast<int64_t>(source_width - 1U) * 256LL
            );
            x0[x] = static_cast<uint32_t>(source_fixed / 256LL);
            x1[x] = std::min(source_width - 1U, x0[x] + 1U);
            x_weight[x] = static_cast<uint32_t>(source_fixed % 256LL);
        }

        for (uint32_t y = 0; y < destination_height; ++y) {
            int64_t source_fixed =
                (static_cast<int64_t>(2U * y + 1U) * source_height * 128LL) /
                    destination_height -
                128LL;
            source_fixed = std::clamp<int64_t>(
                source_fixed,
                0,
                static_cast<int64_t>(source_height - 1U) * 256LL
            );
            const uint32_t y0 = static_cast<uint32_t>(source_fixed / 256LL);
            const uint32_t y1 = std::min(source_height - 1U, y0 + 1U);
            const uint32_t y_weight = static_cast<uint32_t>(source_fixed % 256LL);
            uint8_t* output_row = destination + static_cast<size_t>(y) * destination_stride;
            for (uint32_t x = 0; x < destination_width; ++x) {
                const uint32_t inverse_x = 256U - x_weight[x];
                const uint32_t inverse_y = 256U - y_weight;
                const size_t top_left =
                    (static_cast<size_t>(y0) * source_width + x0[x]) * 3U;
                const size_t top_right =
                    (static_cast<size_t>(y0) * source_width + x1[x]) * 3U;
                const size_t bottom_left =
                    (static_cast<size_t>(y1) * source_width + x0[x]) * 3U;
                const size_t bottom_right =
                    (static_cast<size_t>(y1) * source_width + x1[x]) * 3U;
                for (size_t channel = 0; channel < 3U; ++channel) {
                    const uint32_t top =
                        source[top_left + channel] * inverse_x +
                        source[top_right + channel] * x_weight[x];
                    const uint32_t bottom =
                        source[bottom_left + channel] * inverse_x +
                        source[bottom_right + channel] * x_weight[x];
                    const uint32_t interpolated =
                        top * inverse_y + bottom * y_weight + 32768U;
                    output_row[static_cast<size_t>(x) * 3U + channel] =
                        static_cast<uint8_t>(interpolated >> 16U);
                }
            }
        }
        return AILEN_FACE_OK;
    });
}

uint32_t ailen_face_get_width(ailen_face_handle* handle) noexcept {
    return guard_value<uint32_t>(handle, 0, [](Engine& engine) { return engine.width(); });
}

uint32_t ailen_face_get_height(ailen_face_handle* handle) noexcept {
    return guard_value<uint32_t>(handle, 0, [](Engine& engine) { return engine.height(); });
}

uint32_t ailen_face_get_stride(ailen_face_handle* handle) noexcept {
    return guard_value<uint32_t>(handle, 0, [](Engine& engine) { return engine.stride(); });
}

uint32_t ailen_face_get_pixel_format(ailen_face_handle* handle) noexcept {
    return guard_value<uint32_t>(
        handle, 0, [](Engine& engine) { return engine.pixel_format(); }
    );
}

uint64_t ailen_face_get_frame_generation(ailen_face_handle* handle) noexcept {
    return guard_value<uint64_t>(
        handle, 0, [](Engine& engine) { return engine.frame_generation(); }
    );
}

const char* ailen_face_get_current_sequence(ailen_face_handle* handle) noexcept {
    return guard_text(handle, [](Engine& engine) { return engine.current_sequence(); });
}

const char* ailen_face_get_last_error(ailen_face_handle* handle) noexcept {
    if (handle == nullptr) {
        return "invalid face engine handle";
    }
    try {
        std::lock_guard<std::mutex> lock(handle->mutex);
        return copy_abi_text(handle->abi_error[0] != '\0'
            ? handle->abi_error.data()
            : handle->engine.error().c_str());
    } catch (const std::exception& exc) {
        handle->set_abi_error(exc.what());
    } catch (...) {
        handle->set_abi_error("unknown C++ exception while reading native error");
    }
    return copy_abi_text(handle->abi_error.data());
}

}  // extern "C"
