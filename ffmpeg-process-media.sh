#!/bin/bash
# FFmpeg Media Processing Pipeline — Ground Truth Network
# Location: ./ffmpeg/scripts/process_media.sh

set -e

# Configuration
INPUT_DIR="/frigate-media"
OUTPUT_DIR="/output"
SNAPSHOT_DIR="/input/snapshots"
TIMELAPSE_DIR_SUNRISE="/output/timelapse/sunrise"
TIMELAPSE_DIR_SUNSET="/output/timelapse/sunset"
TIMELAPSE_DIR_WEATHER="/output/timelapse/weather"
WATERMARK_TEXT="Ground Truth Network"
TIMELAPSE_FPS=30

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function: Create timelapse from a directory of sorted JPEGs
# Usage: create_timelapse [date] [source_dir]
create_timelapse() {
    local date=${1:-$(date +%Y%m%d)}
    local src_dir=${2:-"$SNAPSHOT_DIR"}
    local input_pattern="${src_dir}/${date}_*.jpg"
    local output_file="${OUTPUT_DIR}/timelapse/timelapse_${date}.mp4"
    mkdir -p "${OUTPUT_DIR}/timelapse"
    
    log_info "Creating timelapse for date: $date"
    
    # Check if we have enough frames
    frame_count=$(ls -1 $input_pattern 2>/dev/null | wc -l)
    if [ "$frame_count" -lt 10 ]; then
        log_warn "Not enough frames ($frame_count) for timelapse on $date"
        return 1
    fi
    
    log_info "Found $frame_count frames"
    
    # Create timelapse with ffmpeg
    ffmpeg -y \
        -framerate $TIMELAPSE_FPS \
        -pattern_type glob \
        -i "$input_pattern" \
        -c:v libx264 \
        -preset medium \
        -crf 22 \
        -threads 2 \
        -pix_fmt yuv420p \
        "$output_file"
    
    if [ $? -eq 0 ]; then
        log_info "Timelapse created: $output_file"
        return 0
    else
        log_error "Failed to create timelapse"
        return 1
    fi
}

# Function: Add watermark to video
add_watermark() {
    local input_file=$1
    local output_file=$2
    local watermark_position=${3:-"10:H-th-10"}  # Bottom left by default
    
    log_info "Adding watermark to: $input_file"
    
    ffmpeg -y \
        -i "$input_file" \
        -vf "drawtext=text='$WATERMARK_TEXT':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=$watermark_position" \
        -c:a copy \
        "$output_file"
    
    if [ $? -eq 0 ]; then
        log_info "Watermarked video created: $output_file"
        return 0
    else
        log_error "Failed to add watermark"
        return 1
    fi
}

# Function: Convert video for stock platform compatibility
convert_for_stock() {
    local input_file=$1
    local output_file=$2
    local platform=${3:-"shutterstock"}  # shutterstock, adobe, pond5
    
    log_info "Converting for platform: $platform"
    
    case $platform in
        shutterstock)
            # Shutterstock: H.264, up to 4K, 25-60fps, <10GB
            ffmpeg -y \
                -i "$input_file" \
                -c:v libx264 \
                -preset medium \
                -crf 23 \
                -threads 2 \
                -pix_fmt yuv420p \
                -r 30 \
                -c:a aac \
                -b:a 192k \
                "$output_file"
            ;;
        adobe)
            # Adobe Stock: H.264, up to 4K
            ffmpeg -y \
                -i "$input_file" \
                -c:v libx264 \
                -preset medium \
                -crf 22 \
                -threads 2 \
                -pix_fmt yuv420p \
                -r 30 \
                -c:a aac \
                -b:a 192k \
                "$output_file"
            ;;
        pond5)
            # Pond5: H.264, up to 4K
            ffmpeg -y \
                -i "$input_file" \
                -c:v libx264 \
                -preset medium \
                -crf 20 \
                -threads 2 \
                -pix_fmt yuv420p \
                -r 30 \
                -c:a pcm_s16le \
                "$output_file"
            ;;
        *)
            log_error "Unknown platform: $platform"
            return 1
            ;;
    esac
    
    if [ $? -eq 0 ]; then
        log_info "Stock platform video created: $output_file"
        return 0
    else
        log_error "Failed to convert for stock platform"
        return 1
    fi
}

# Function: Extract interesting clips from Frigate events
extract_event_clip() {
    local event_json=$1
    local output_file=$2
    local duration=${3:-10}  # seconds before and after event
    
    log_info "Extracting event clip from: $event_json"
    
    # Parse event JSON (requires jq)
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not installed"
        return 1
    fi
    
    camera=$(jq -r '.camera' "$event_json")
    start_time=$(jq -r '.start_time' "$event_json")
    
    # Find source video
    video_file="${INPUT_DIR}/${camera}/$(date -d @${start_time} +%Y-%m-%d)/${start_time}.mp4"
    
    if [ ! -f "$video_file" ]; then
        log_error "Source video not found: $video_file"
        return 1
    fi
    
    # Extract clip
    ffmpeg -y \
        -ss $(($start_time - $duration)) \
        -i "$video_file" \
        -t $((2 * $duration)) \
        -c copy \
        "$output_file"
    
    if [ $? -eq 0 ]; then
        log_info "Event clip extracted: $output_file"
        return 0
    else
        log_error "Failed to extract event clip"
        return 1
    fi
}

# Function: Create storm highlight reel
create_storm_reel() {
    local date=${1:-$(date +%Y%m%d)}
    local output_file="${OUTPUT_DIR}/storm_reel_${date}.mp4"
    
    log_info "Creating storm highlight reel for: $date"
    
    # Find all storm event clips
    storm_clips=$(ls -1 "${INPUT_DIR}/"*"/events/storm_"*"${date}"*.mp4 2>/dev/null)
    
    if [ -z "$storm_clips" ]; then
        log_warn "No storm clips found for $date"
        return 1
    fi
    
    # Create concat file
    concat_file="${OUTPUT_DIR}/concat_${date}.txt"
    > "$concat_file"
    
    for clip in $storm_clips; do
        echo "file '$clip'" >> "$concat_file"
    done
    
    # Concatenate clips
    ffmpeg -y \
        -f concat \
        -safe 0 \
        -i "$concat_file" \
        -c copy \
        "$output_file"
    
    rm "$concat_file"
    
    if [ $? -eq 0 ]; then
        log_info "Storm reel created: $output_file"
        return 0
    else
        log_error "Failed to create storm reel"
        return 1
    fi
}

# Function: Create timelapse from a named subset (sunrise/sunset/weather)
# Usage: timelapse-subset <subset> <date>
#   subset: sunrise | sunset | weather
create_timelapse_subset() {
    local subset=$1
    local date=${2:-$(date +%Y%m%d)}
    local src_dir="/camera-raw/${date}/${subset}"   # HA snapshots land here
    local alt_dir="/output/timelapse/${subset}"      # fallback if HA used output dir
    local output_file="${OUTPUT_DIR}/timelapse/${subset}_${date}.mp4"

    # Try mounted HA snapshot path first, fall back to timelapse dir
    if [ -d "$src_dir" ] && ls "$src_dir"/*.jpg &>/dev/null; then
        input_dir="$src_dir"
    elif [ -d "$alt_dir" ] && ls "$alt_dir"/${date}_*.jpg &>/dev/null; then
        input_dir="$alt_dir"
    else
        log_warn "No $subset frames found for $date"
        return 1
    fi

    frame_count=$(ls -1 "$input_dir"/*.jpg 2>/dev/null | wc -l)
    log_info "Creating $subset timelapse for $date ($frame_count frames)"

    # Sort frames and create an input list for ffmpeg (avoids glob ordering issues)
    list_file="/tmp/frames_${subset}_${date}.txt"
    ls -v "$input_dir"/*.jpg 2>/dev/null | while read f; do echo "file '$f'"; done > "$list_file"

    ffmpeg -y \
        -f concat -safe 0 \
        -i "$list_file" \
        -r $TIMELAPSE_FPS \
        -c:v libx264 \
        -preset medium \
        -crf 22 \
        -threads 2 \
        -pix_fmt yuv420p \
        -vf "drawtext=text='${WATERMARK_TEXT} | ${subset^} %{localtime\\:%Y-%m-%d}':fontsize=28:fontcolor=white@0.8:box=1:boxcolor=black@0.4:boxborderw=6:x=20:y=H-th-20" \
        "$output_file"

    rm -f "$list_file"
    [ $? -eq 0 ] && log_info "Subset timelapse: $output_file" || log_error "Subset timelapse failed"
}

# Main execution
case "${1:-help}" in
    timelapse)
        create_timelapse "$2" "$3"
        ;;
    timelapse-subset)
        create_timelapse_subset "$2" "$3"
        ;;
    watermark)
        add_watermark "$2" "$3" "$4"
        ;;
    stock)
        convert_for_stock "$2" "$3" "$4"
        ;;
    event)
        extract_event_clip "$2" "$3" "$4"
        ;;
    storm-reel)
        create_storm_reel "$2"
        ;;
    full-pipeline)
        DATE=${2:-$(date +%Y%m%d)}
        log_info "Running full pipeline for $DATE"

        TIMELAPSE="${OUTPUT_DIR}/timelapse/timelapse_${DATE}.mp4"
        create_timelapse "$DATE"

        WATERMARKED="${OUTPUT_DIR}/timelapse/timelapse_${DATE}_wm.mp4"
        add_watermark "$TIMELAPSE" "$WATERMARKED"

        convert_for_stock "$WATERMARKED" "${OUTPUT_DIR}/library/timelapse_${DATE}_stock.mp4" "shutterstock"

        # Compile golden hour subsets if they exist
        create_timelapse_subset "sunrise" "$DATE" || true
        create_timelapse_subset "sunset" "$DATE" || true

        create_storm_reel "$DATE" || true

        log_info "Full pipeline complete for $DATE"
        ;;
    *)
        echo "Usage: $0 {timelapse|timelapse-subset|watermark|stock|event|storm-reel|full-pipeline} [args...]"
        echo ""
        echo "Commands:"
        echo "  timelapse [date] [src_dir]              - Full-day timelapse from snapshots"
        echo "  timelapse-subset <subset> [date]        - subset: sunrise|sunset|weather"
        echo "  watermark <input> <output> [pos]        - Add watermark"
        echo "  stock <input> <output> [platform]       - Convert for stock (shutterstock/adobe/pond5)"
        echo "  event <json> <output> [duration]        - Extract event clip"
        echo "  storm-reel [date]                       - Storm highlight reel"
        echo "  full-pipeline [date]                    - Full daily processing pipeline"
        ;;
esac
