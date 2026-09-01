cmake_minimum_required(VERSION 3.16)
project(ailen_face_engine VERSION 0.2.0 LANGUAGES CXX)

add_library(ailen_face_engine SHARED src/face_engine.cpp)
target_compile_features(ailen_face_engine PUBLIC cxx_std_17)
target_include_directories(
    ailen_face_engine
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

find_package(JPEG REQUIRED)
target_link_libraries(ailen_face_engine PRIVATE JPEG::JPEG)
target_compile_definitions(ailen_face_engine PRIVATE AILEN_FACE_ENGINE_BUILD=1)

if(MSVC)
    target_compile_options(ailen_face_engine PRIVATE /W4 /permissive-)
    set_target_properties(ailen_face_engine PROPERTIES OUTPUT_NAME "ailen_face_engine")
else()
    target_compile_options(ailen_face_engine PRIVATE -Wall -Wextra -Wpedantic)
    set_target_properties(ailen_face_engine PROPERTIES OUTPUT_NAME "ailen_face_engine")
endif()

install(TARGETS ailen_face_engine)
install(FILES include/ailen_face_engine.h DESTINATION include)
