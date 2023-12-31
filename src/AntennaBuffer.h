//
// Created by Alessio Magro on 05/05/2022.
//

#ifndef AAVS_DAQ_ANTENNABUFFER_H
#define AAVS_DAQ_ANTENNABUFFER_H

#include <cstdlib>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>
#include <cmath>
#include <string>
#include <unordered_map>
#include <sys/mman.h>
#include <cfloat>

#include "DAQ.h"

// ----------------- Antenna Buffer container and helpers -----------------
template <class T> class AntennaBufferDataContainer
{
public:
    struct AntennaBufferStructure {
        uint16_t tile;
        T* data;
    };

    // Class constructor
    AntennaBufferDataContainer(uint16_t nof_tiles, uint16_t nof_antennas, uint32_t nof_samples, uint8_t nof_pols)
    {
        // Set local variables
        this->nof_antennas = nof_antennas;
        this->nof_samples = nof_samples;
        this->nof_tiles = nof_tiles;
        this->nof_pols = nof_pols;
        antennas_per_fpga = nof_antennas / 2;

        size_t malloc_size = nof_antennas * nof_pols * (size_t) nof_samples * sizeof(T);

        // Allocate buffer
        antenna_buffer_data = (AntennaBufferStructure *) malloc(nof_tiles * sizeof(AntennaBufferStructure));
        for(unsigned i = 0; i < nof_tiles; i++) {
            allocate_aligned((void **) &(antenna_buffer_data[i].data), (size_t) CACHE_ALIGNMENT, malloc_size);

            // Lock memory
            if (mlock(antenna_buffer_data[i].data, malloc_size) == -1)
                perror("Could not lock memory");
        }

        // Reset antenna information
        clear();

        // Reserve required number of buckets in map
        tile_map.reserve(nof_tiles);
    }

    // Class destructor
    ~AntennaBufferDataContainer() {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(antenna_buffer_data[i].data);
        free(antenna_buffer_data);
    }

public:

    // Set callback function
    void setCallback(DataCallback callback) {
        this->callback = callback;
    }

    // Add data to buffer
    void add_data(T* data_ptr, uint16_t tile, uint32_t start_sample_index,
                  uint32_t samples, double timestamp, uint8_t fpga_id) {

        // Get current tile index
        unsigned int tile_index;
        if (tile_map.find(tile) != tile_map.end())
            tile_index = tile_map[tile];
        else {
            tile_index = (unsigned int) tile_map.size();

            if (tile_index == nof_tiles) {
                LOG(WARN, "Cannot process tile %d, channel consumer configured for %d tiles", tile, nof_tiles);
                return;
            }

            tile_map[tile] = tile_index;
            antenna_buffer_data[tile_index].tile = tile;
        }

        // Copy packet content to buffer
        // Packet data is in groups of 4 samples, each with nof_pols
        // So antennas have a stride of 4 * nof_pols * sizeof(T), with alternating antennas
        for(unsigned a = 0; a < antennas_per_fpga; a++)
        {
            T* dst_ptr = antenna_buffer_data[tile_index].data +
                    ((antennas_per_fpga * fpga_id + a) * nof_samples + start_sample_index) * nof_pols;

            for(unsigned s = 0; s < samples; s+=4)
            {
                memcpy(dst_ptr,
                       data_ptr + (s * antennas_per_fpga + a * 4) * nof_pols,
                       nof_pols * 4 * sizeof(T));
                dst_ptr += 4 * nof_pols;
            }
        }

        // Update timing
        if (this->timestamp > timestamp)
            this->timestamp = timestamp;

        // Update number of packets in container
        nof_packets++;
    }

    // Clear buffer and antenna information
    void clear() {
        // Clear buffer, set all content to 0
        for (unsigned i = 0; i < nof_tiles; i++)
            memset(antenna_buffer_data[i].data, 0, nof_antennas * nof_pols * nof_samples);

        timestamp = DBL_MAX;
        nof_packets = 0;
    }

    // Push data to callback
    void persist_container() {

        // If a callback is defined, call it and return
        if (callback == nullptr) {
            clear();
            LOG(WARN, "No callback for antenna buffer data defined");
            return;
        }

        // Call callback for each tile
        for(unsigned i = 0; i < nof_tiles; i++)
            callback((uint32_t *) antenna_buffer_data[i].data, timestamp,
                     antenna_buffer_data[i].tile, 0);
        clear();
    }

public:
    uint32_t nof_packets = 0;

private:
    // Parameters
    uint16_t nof_tiles;
    uint16_t nof_antennas;
    uint16_t antennas_per_fpga;
    uint32_t nof_samples;
    uint8_t  nof_pols;

    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Timestamp
    double timestamp = DBL_MAX;

    // Data container
    AntennaBufferStructure *antenna_buffer_data;

    // Callback function
    DataCallback callback = nullptr;

};

// ----------------- Antenna Buffer data consumer -------------------------

class AntennaBuffer: public DataConsumer {

public:
    // Override setDataCallback
    void setCallback(DataCallback callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering funtion to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Function called when a burst stream capture has finished
    void onStreamEnd() override;

    // Override clean up methode
    void cleanUp() override;

private:
    AntennaBufferDataContainer<uint8_t> **containers = nullptr;
    unsigned nof_containers = 4;
    unsigned current_container = 0;
    unsigned current_buffer = 0;

    int current_packet_index = -1;

    // Antenna information object
    unsigned not_received_samples = 0;
    unsigned nof_required_samples = 0;

    double timestamp_scale = 1 / 800.0e6;

    // Data setup
    uint16_t nof_antennas = 0;
    uint8_t nof_pols = 0;
    uint16_t nof_tiles = 0;
    uint32_t nof_samples = 0;
};

// Expose class factory for AntennaBufferData
extern "C" DataConsumer *antennabuffer() { return new AntennaBuffer; }

#endif //AAVS_DAQ_ANTENNABUFFER_H
