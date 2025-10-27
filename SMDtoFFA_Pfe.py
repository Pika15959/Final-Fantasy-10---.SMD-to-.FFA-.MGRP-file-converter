import os
import struct
import sys

# Constants for the mathematical conversion
DIVISOR_1 = 0.00030518
DIVISOR_2 = 0.001534

# --- DATA STREAM ENCODER (Unchanged) ---
def encode_single_delta(delta):
    if -64 <= delta <= 63:
        return bytes([delta & 0x7F])
    elif -8192 <= delta <= 8191:
        if delta < 0:
            delta += (1 << 14)
        byte1 = 0xC0 | (delta & 0x3F)
        byte2 = (delta >> 6) & 0xFF
        return bytes([byte1, byte2])
    else:
        clamped_delta = max(-8192, min(delta, 8191))
        return encode_single_delta(clamped_delta)

# --- [ FUNCTION EDITED ] ---
def create_mode3_block(value_timeline):
    if not value_timeline:
        return b'\x02\x00' # This is already 2 bytes (even)
    deltas = []
    accumulator = 0
    for value in value_timeline:
        delta = value - accumulator
        deltas.append(delta)
        accumulator = value
        
    encoded_payload = bytearray()
    i = 0
    while i < len(deltas):
        current_delta = deltas[i]
        run_length = 1
        for j in range(i + 1, len(deltas)):
            if deltas[j] == current_delta:
                run_length += 1
            else:
                break
        
        if run_length >= 2:
            encoded_payload.extend(encode_single_delta(current_delta))
            repeats_to_encode = run_length - 1
            while repeats_to_encode > 0:
                chunk_repeats = min(repeats_to_encode, 64)
                encoded_value = chunk_repeats - 1
                rle_command = 0x80 | encoded_value
                encoded_payload.append(rle_command)
                repeats_to_encode -= chunk_repeats
            i += run_length
        else:
            encoded_payload.extend(encode_single_delta(current_delta))
            i += 1
            
    # --- [ NEW LOGIC START ] ---
    # Check if the payload length is odd. The header is 2 bytes (even),
    # so an odd payload would make the total block size odd.
    if len(encoded_payload) % 2 != 0:
        # Add a single null padding byte to make the payload even.
        encoded_payload.append(0x00)
    
    # Now, calculate the final total block size, which is guaranteed to be even.
    total_block_size = len(encoded_payload) + 2
    # --- [ NEW LOGIC END ] ---
    
    header = struct.pack('<H', total_block_size)
    return header + encoded_payload

def get_mode_code(data_list):
    if len(set(data_list)) <= 1:
        static_value = data_list[0] if data_list else 0
        return "00" if static_value == 0 else "10"
    else:
        return "11"

# --- Animation Chunk Encoder (Unchanged) ---
def encode_data_chunk(chunk_data, chunk_num):
    print(f" > Encoding Chunk #{chunk_num}...")
    property_order = ['rotX', 'rotY', 'rotZ', 'posX', 'posY', 'posZ']
    if not chunk_data:
        print("   Chunk contains no data. Skipping.")
        return None
        
    all_bone_modes = []
    big_chunk_2_data = bytearray()
    
    for bone_id in sorted(chunk_data.keys()):
        bone_properties = chunk_data[bone_id]
        mode_codes = [get_mode_code(bone_properties[prop]) for prop in property_order]
        combined_modes = "".join(mode_codes) + "010101"
        all_bone_modes.append(combined_modes)
        
        for i, prop_key in enumerate(property_order):
            data_list = bone_properties[prop_key]
            mode = mode_codes[i]
            if mode == "10":
                static_value = data_list[0]
                big_chunk_2_data.extend(struct.pack('<h', static_value))
            elif mode == "11":
                data_block = create_mode3_block(data_list)
                big_chunk_2_data.extend(data_block)
                
    big_chunk_1_string = "".join(all_bone_modes)
    remainder = len(big_chunk_1_string) % 8
    if remainder != 0:
        big_chunk_1_string += '0' * (8 - remainder)
        
    swapped_chunk_1 = ""
    for i in range(0, len(big_chunk_1_string), 4):
        chunk = big_chunk_1_string[i:i+4]
        swapped_chunk_1 += (chunk[2:4] + chunk[0:2]) if len(chunk) == 4 else chunk
        
    doubly_swapped_chunk_1 = ""
    for i in range(0, len(swapped_chunk_1), 8):
        chunk = swapped_chunk_1[i:i+8]
        doubly_swapped_chunk_1 += (chunk[4:8] + chunk[0:4]) if len(chunk) == 8 else chunk
        
    final_byte_data_chunk1 = bytearray(int(doubly_swapped_chunk_1[i:i+8], 2) for i in range(0, len(doubly_swapped_chunk_1), 8))
    
    num_bones = len(chunk_data)
    first_bone_id = sorted(chunk_data.keys())[0]
    num_frames = len(chunk_data[first_bone_id][property_order[0]])
    size_of_bone_mode_chunk = len(final_byte_data_chunk1)
    pointer_val = size_of_bone_mode_chunk + 0x18
    
    header = bytearray(32)
    header[4:8] = b'\x77\x77\x77\x77'
    header[12] = 0x00
    header[13] = 0x1E
    header[16:20] = struct.pack('<I', 0x18)
    
    frame_bytes = struct.pack('<H', num_frames)
    header[2:4] = frame_bytes
    header[8:10] = frame_bytes
    header[10] = num_bones & 0xFF
    
    pointer_bytes = struct.pack('<H', pointer_val)
    header[20:22] = pointer_bytes
    
    final_chunk_data = header + final_byte_data_chunk1 + big_chunk_2_data
    return final_chunk_data + (b'\x77' * 16)


# --- Main processing and file assembly function (Unchanged) ---
def process_animation_file(filepath, chunk_sizes):
    filename = os.path.basename(filepath)
    output_filepath = os.path.splitext(filepath)[0] + '.ffa'
    print(f"\n{'='*25} Processing: {filename} {'='*25}")
    
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Could not read file as text: {e}")
        return

    full_bone_data = {}
    property_names = ['posX', 'posY', 'posZ', 'rotX', 'rotY', 'rotZ']
    in_skeleton_section = False
    for line_text in lines:
        stripped_line = line_text.strip()
        if stripped_line == "skeleton": in_skeleton_section = True; continue
        if stripped_line == "end": in_skeleton_section = False; continue
        if not in_skeleton_section or not stripped_line or stripped_line.lower().startswith("time"): continue
        
        parts = stripped_line.split()
        if len(parts) < 7: continue
        
        try:
            bone_id = int(parts[0])
            group1 = [int(round(float(p) / DIVISOR_1)) for p in parts[1:4]]
            group2 = [int(round(float(p) / DIVISOR_2)) for p in parts[4:7]]
            all_processed_numbers = group1 + group2
            
            if bone_id not in full_bone_data:
                full_bone_data[bone_id] = {prop: [] for prop in property_names}
                
            for i, prop_name in enumerate(property_names):
                full_bone_data[bone_id][prop_name].append(all_processed_numbers[i])
        except (ValueError, IndexError):
            continue

    if not full_bone_data:
        print("No valid animation data was found in this file.")
        return

    num_bones_total = len(full_bone_data)
    first_bone_id_total = sorted(full_bone_data.keys())[0]
    total_frames = len(full_bone_data[first_bone_id_total][property_names[0]])
    print(f"📊 Found {num_bones_total} bone(s) and {total_frames} total frame(s) of animation.")
    print("-" * 35)

    # === PHASE 1: Generate all animation chunks in memory ===
    encoded_chunks = []
    start_frame = 0
    for i, chunk_len in enumerate(chunk_sizes):
        if start_frame >= total_frames:
            break
        end_frame = start_frame + chunk_len
        sliced_data = {}
        for bone_id, properties in full_bone_data.items():
            sliced_data[bone_id] = {}
            for prop_name, values in properties.items():
                sliced_data[bone_id][prop_name] = values[start_frame:end_frame]
                
        chunk_binary_data = encode_data_chunk(sliced_data, i + 1)
        if chunk_binary_data:
            encoded_chunks.append(chunk_binary_data)
        start_frame = end_frame
    
    num_chunks = len(encoded_chunks)
    if num_chunks == 0:
        print("\nNo animation chunks were generated. Nothing to save.")
        return
        
    # === [NEW] PHASE 1.5: Add alignment padding to the final chunk ===
    # Calculate the offset where the next section (BUMP) would start
    post_chunk_offset = 16 + sum(len(c) for c in encoded_chunks)
    
    # Determine how many bytes are needed to align to a 4-byte boundary
    padding_needed = (4 - (post_chunk_offset % 4)) % 4
    
    if padding_needed > 0:
        print(f" > Aligning sections: Adding {padding_needed} byte(s) of 0x77 padding...")
        padding = b'\x77' * padding_needed
        # Append padding to the last chunk's data as a new bytearray
        encoded_chunks[-1] = encoded_chunks[-1] + padding

    # === PHASE 2: Calculate offsets for all sections ===
    chunk_offsets = []
    current_offset = 16
    for chunk in encoded_chunks:
        chunk_offsets.append(current_offset)
        current_offset += len(chunk)
    
    bump_section_offset = current_offset
    pop_section_offset = bump_section_offset + (num_chunks * 16)
    snap_section_offset = pop_section_offset + (num_chunks * 12)
    end_line_offset = snap_section_offset + (num_chunks * 16)

    # === PHASE 3: Assemble the final file in a bytearray ===
    final_file_data = bytearray()

    # 1. Initial Header (will be patched later)
    final_file_data.extend(b'\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

    # 2. All Animation Chunks
    for chunk in encoded_chunks:
        final_file_data.extend(chunk)

    # 3. BUMP Section
    for i in range(num_chunks):
        final_file_data.extend(b'\x00\x00\x00\x00\x02\x00\x00\x00')
        final_file_data.extend(struct.pack('<I', chunk_offsets[i]))
        final_file_data.extend(struct.pack('<I', chunk_offsets[i] + 8))

    # 4. POP Section
    for i in range(num_chunks):
        line = bytearray(12)
        line[2:4] = b'\x01\x00'
        line[3] = i & 0xFF
        line[8:12] = b'\x00\x01\x00\x00'
        final_file_data.extend(line)

    # 5. SNAP Section
    for i in range(num_chunks):
        pop_line_offset = pop_section_offset + (i * 12)
        bump_line_offset = bump_section_offset + (i * 16) 
        final_file_data.extend(struct.pack('<I', bump_line_offset))
        final_file_data.extend(b'\x01\x00\x0A\x00')
        final_file_data.extend(struct.pack('<I', pop_line_offset))
        final_file_data.extend(struct.pack('<I', pop_line_offset + 2))

    # 6. END Line
    end_line = bytearray(20)
    end_line[0:4] = b'\x40\x44\x10\x40'
    end_line[8] = num_chunks & 0xFF
    end_line[10] = num_chunks & 0xFF
    end_line[12:16] = struct.pack('<I', snap_section_offset)
    end_line[16:20] = struct.pack('<I', bump_section_offset)
    final_file_data.extend(end_line)
    
    # 7. Final Patch: Update the pointer in the initial header
    final_file_data[12:16] = struct.pack('<I', end_line_offset)

    # === PHASE 4: Write to file ===
    try:
        with open(output_filepath, 'wb') as f_out:
            f_out.write(final_file_data)
        print(f"\nSUCCESS: Saved complete file structure to '{os.path.basename(output_filepath)}' 👍")
    except IOError as e:
        print(f"\nERROR: Could not write to file '{output_filepath}': {e}")


# --- MAIN EXECUTION BLOCK (Unchanged) ---
if __name__ == "__main__":
    files_to_process = [f for f in sys.argv[1:] if os.path.isfile(f)] if len(sys.argv) > 1 else []
    if not files_to_process:
        print("Usage: Drag one or more animation files onto this script's icon.")
        input("\nPress Enter to exit.")
        sys.exit()
        
    chunk_input = input("Enter chunk lengths, separated by commas (e.g., 10,35,3): ")
    try:
        chunk_sizes = [int(size.strip()) for size in chunk_input.split(',')]
        if any(size <= 0 for size in chunk_sizes):
            raise ValueError("Chunk sizes must be positive integers.")
    except ValueError as e:
        print(f"\nInvalid input: {e}. Please enter positive, comma-separated numbers.")
        input("\nPress Enter to exit.")
        sys.exit()
        
    for filepath in files_to_process:
        process_animation_file(filepath, chunk_sizes)
        
    print("\n\n--- All files and chunks processed. ---")
    input("\nPress Enter to exit.")
