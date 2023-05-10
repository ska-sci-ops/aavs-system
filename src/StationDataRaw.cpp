//
// Created by Alessio Magro on 14/05/2018.
//

#include <fcntl.h>
#include <sys/mman.h>
#include <cfloat>
#include <limits.h>
#include "StationDataRaw.h"
#include "SPEAD.h"

// -------------------------------------------------------------------------------------------------------------
// STATION DATA CONSUMER
// -------------------------------------------------------------------------------------------------------------

// Initialise station data consumer
bool StationRawData::initialiseConsumer(json configuration)
{

    // Check that all required keys are present
    if (!(key_in_json(configuration, "start_channel"))) {
        LOG(FATAL, "Missing configuration item start_channel");
        return false;
    }

    if (!(key_in_json(configuration, "nof_channels"))) {
        LOG(FATAL, "Missing configuration item nof_channels");
        return false;
    }

    if (!(key_in_json(configuration, "nof_samples"))) {
        LOG(FATAL, "Missing configuration item nof_samples");
        return false;
    }

    if (!(key_in_json(configuration, "transpose_samples"))) {
        LOG(FATAL, "Missing configuration item transpose_samples");
        return false;
    }

    if (!(key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item max_packet_size");
        return false;
    }

    if (!(key_in_json(configuration, "capture_start_time"))) {
        LOG(FATAL, "Missing configuration item capture_start_time");
        return false;
    }


    // Set local values
    start_channel = configuration["start_channel"];
    nof_channels = configuration["nof_channels"];
    nof_samples  = configuration["nof_samples"];
    transpose = (configuration["transpose_samples"] == 1);
    packet_size = configuration["max_packet_size"];
    capture_start_time = round((double) configuration["start_time"]);;
    nof_pols = 2;

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) nof_samples / 8);

    // Create double buffer
    double_buffer= new StationRawDoubleBuffer(start_channel, nof_samples, nof_channels, nof_pols, transpose);

    // Create and persister
    persister = new StationRawPersister(double_buffer);
    persister->startThread();

    // All done
    return true;
}

// Cleanup function
void StationRawData::cleanUp()
{
    // Stop cross correlator thread
    if (persister != nullptr)
        persister->stop();

    // Destroy instances
    delete persister;
    delete double_buffer;
}

// Set callback
void StationRawData::setCallback(DataCallbackDynamic callback)
{
    if (persister != nullptr)
        persister->setCallback(callback);
}

// Packet filter
bool StationRawData::packetFilter(unsigned char *udp_packet)
{
    // Unpack SPEAD Header (or try to)
    uint64_t hdr = SPEAD_HEADER(udp_packet);

    // Check that this is in fact a SPEAD packet and that the correct
    // version is being used
    if ((SPEAD_GET_MAGIC(hdr) != SPEAD_MAGIC) ||
        (SPEAD_GET_VERSION(hdr) != SPEAD_VERSION) ||
        (SPEAD_GET_ITEMSIZE(hdr) != SPEAD_ITEM_PTR_WIDTH) ||
        (SPEAD_GET_ADDRSIZE(hdr) != SPEAD_HEAP_ADDR_WIDTH))
        return false;

    // Check whether this is a Station Beam packet
    for (unsigned short i = 0; i < SPEAD_GET_NITEMS(hdr); i++)
        if (SPEAD_ITEM_ID(SPEAD_ITEM(udp_packet, i)) == 0x1011)
            return true;

    // Did not find item 0x1011, not a station beam packet
    return false;
}

// Get and process packet
bool StationRawData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        return false;

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint64_t packet_counter   = 0;
    uint16_t logical_channel_id = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint64_t payload_length = 0;
    uint64_t frequency = 0;
    uint16_t beam_id = 0;
    uint16_t frequency_id = 0;
    uint8_t substation_id = 0;
    uint8_t subarray_id = 0;
    uint16_t station_id = 0;
    uint16_t nof_contributing_antennas = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    for(unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                logical_channel_id = (uint16_t) ((SPEAD_ITEM_ADDR(item) >> 32) & 0xFFFF); // 16-bits
                packet_counter = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFFFF); // 32-bits
                break;
            }
            case 0x0004: // Payload length
            {
                payload_length = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x1027: // Sync time
            {
                sync_time = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x1600: // Timestamp
            {
                timestamp = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x1011: // Frequency
            {
                frequency = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x3000: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                beam_id = (uint16_t) ((val >> 16) & 0xFFFF);
                frequency_id = (uint16_t) (val & 0xFFFF);
                break;
            }
            case 0x3001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                substation_id = (uint8_t) ((val >> 40) & 0xFF);
                subarray_id = (uint8_t) ((val >> 32) & 0xFF);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_contributing_antennas = (uint16_t) (val & 0xFFFF);
                break;
            }
            case 0x3300: // Payload offset
            {
                payload_offset = (uint32_t) SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2004:
                break;
            default:
                LOG(WARN, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // Check whether timestamp counter has rolled over
    if (timestamp == 0 && logical_channel_id == 0) {
        timestamp_rollover += 1;
        timestamp += timestamp_rollover << 48;
    }
    else if (timestamp == 0)
        timestamp += timestamp_rollover << 48;
    else
        // Multiply packet_counter by rollover counts
        timestamp += timestamp_rollover << 48;

    // Calculate packet time
    double packet_time = sync_time + timestamp * 1.0e-9; // timestamp_scale;

    // Check whether packet timestamp is past start time
    if (capture_start_time > 0 and packet_time < capture_start_time) {
        ring_buffer -> pull_ready();
        return true;
    }

    // Calculate number of samples in packet
    auto samples_in_packet = static_cast<uint32_t>((payload_length - payload_offset) / (sizeof(uint16_t) * nof_pols));

    // Check whether packet counter has rolled over
    if (packet_counter == 0 && logical_channel_id == 0) {
        rollover_counter += 1;
        packet_counter += rollover_counter << 32;
    }
    else if (packet_counter == 0)
        packet_counter += (rollover_counter + 1) << 32;
    else
        // Multiply packet_counter by rollover counts
        packet_counter += rollover_counter << 32;

    // If this is channel of interest, save, otherwise ignore
    if (logical_channel_id >= start_channel && logical_channel_id < start_channel + nof_channels)

        // We have processed the packet items, send data to packet counter
        double_buffer -> write_data(samples_in_packet,
                                    logical_channel_id,
                                    packet_counter,
                                    reinterpret_cast<uint16_t *>(payload + payload_offset),
                                    packet_time, 
				    frequency & 0xFFFFFFFF);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// -------------------------------------------------------------------------------------------------------------
// STATION DOUBLE BUFFER
// -------------------------------------------------------------------------------------------------------------

// Default double buffer constructor
StationRawDoubleBuffer::StationRawDoubleBuffer(uint16_t start_channel, uint32_t nof_samples,
                                               uint32_t nof_channels, uint8_t nof_pols,
                                               bool transpose, uint8_t nbuffers) :
        start_channel(start_channel), nof_samples(nof_samples), nof_channels(nof_channels),
        nof_pols(nof_pols), transpose(transpose), nof_buffers(nbuffers)
{
    // Allocate the double buffer
    allocate_aligned((void **) &double_buffer, (size_t) CACHE_ALIGNMENT, nbuffers * sizeof(StationRawBuffer));

    // Initialise and allocate buffers in each struct instance
    for(unsigned i = 0; i < nof_buffers; i++)
    {
        // Allocate buffer. Note: using alignment of page size for Direct IO
        allocate_aligned((void **) &double_buffer[i].data, (size_t) PAGE_ALIGNMENT,
                         nof_pols * nof_channels * nof_samples * sizeof(uint16_t));

        // Create mutex
        double_buffer[i].mutex = new std::mutex;

        // Initialise
        clear(i);
    }
    
    // Initialise producer and consumer
    producer = 0;
    consumer = 0;

    // Set up timing variables
    tim.tv_sec  = 0;
    tim.tv_nsec = 1000;
}

// Class destructor
StationRawDoubleBuffer::~StationRawDoubleBuffer()
{
    for(unsigned i = 0; i < nof_buffers; i++)
    {
        delete double_buffer[i].mutex;
        free(double_buffer[i].data);
    }
    free(double_buffer);
}

// Write data to buffer
void StationRawDoubleBuffer::write_data(uint32_t samples,  uint32_t channel, uint64_t packet_counter,
                                        uint16_t *data_ptr, double timestamp, uint32_t frequency)
{
    // Check whether the current consumer buffer is empty, and if so set index of the buffer
    if (double_buffer[producer].sample_index == 0) {
        double_buffer[producer].sample_index = packet_counter;
        double_buffer[producer].seq_number = buffer_counter++;
    }

    // Check if we are receiving a packet from a previous buffer, if so place in previous buffer
    else if (double_buffer[producer].sample_index > packet_counter)
    {
        // Select buffer to place data into
        int local_producer = (producer == 0) ? nof_buffers - 1 : (producer - 1);

        // Check if packet belongs in selected buffer
        auto local_index = double_buffer[local_producer].sample_index;
        if (local_index > packet_counter)
            // Packet belongs to an older buffer (or is invalid). Ignoring
            return;

        // Copy data into selected buffer
        this->process_data(local_producer, packet_counter, samples, channel, data_ptr, timestamp, frequency);

        // Ready from packet
        return;
    }

    // Check if packet counter is within current buffer or if we have skipped buffer boundary
    else if (packet_counter - double_buffer[producer].sample_index >= nof_samples / samples)
    {
        // Store current buffer's index
        uint64_t current_index = double_buffer[producer].sample_index;

        // We have skipped buffer borders, mark buffer before previous one as ready and switch to next one
        int local_producer = (producer < 2) ? (producer - 2) + nof_buffers : (producer - 2);
        if (double_buffer[local_producer].sample_index != 0)
            double_buffer[local_producer].ready = true;

        // Update producer pointer
        producer = (producer + 1) % nof_buffers;

        // Wait for next buffer to become available
        long elapsed_time = 0;

        // Lock buffer
        double_buffer[producer].mutex -> lock();

        // If the buffer index is not 0 (still need to be consumed), wait for a while to give time for the
        // consumer process it. Whilst waiting, unlock the buffer. If enough time passes, then the buffer
        // will be acquired regardless of whether it contains unprocessed data
        for(;;) {

            // Check if buffer can be used
            if (double_buffer[producer].sample_index == 0)
                break;

            // Buffer not consumed yet, wait for a while (unlock during sleep)
            double_buffer[producer].mutex->unlock();
            nanosleep(&tim, &tim2);
            double_buffer[producer].mutex->lock();
            elapsed_time += tim.tv_nsec - tim2.tv_nsec;

            // Overwriting a buffer, issue warning and clear buffer
            if (elapsed_time >= 1e4) {
                LOG(WARN, "WARNING: Overwriting buffer %d with %d samples by buffer %d!",
                    double_buffer[producer].seq_number, double_buffer[producer].nof_packets, buffer_counter);
                clear(producer);
		break;
            }
        }

    	// Clear buffer and start using
        double_buffer[producer].sample_index = current_index + nof_samples / samples;
        double_buffer[producer].seq_number = buffer_counter++;

        // Unlock double buffer
        double_buffer[consumer].mutex -> unlock();
    }

    // Copy data to buffer
    process_data(producer, packet_counter, samples, channel, data_ptr, timestamp, frequency);

    // Update buffer index if required
    if (double_buffer[producer].sample_index > packet_counter)
        double_buffer[producer].sample_index = packet_counter;
}

inline void StationRawDoubleBuffer::process_data(int producer_index, uint64_t packet_counter, uint32_t samples,
                                                 uint32_t channel, uint16_t *data_ptr, double timestamp, uint32_t frequency)
{
    // Copy data from packet to buffer
    // If number of channels is 1, or if data is not being transposed, then simply copy the entire buffer to its destination
    if (nof_channels == 1 || !transpose) {
        auto dst = this->double_buffer[producer_index].data + channel * nof_samples * nof_pols +
                                (packet_counter - this->double_buffer[producer_index].sample_index) * samples * nof_pols;
        memcpy(dst,
               data_ptr,
               nof_pols * samples * sizeof(uint16_t));
    }
    else {
        // We need to transpose the data
        // dst is in sample/channel/pol order, so we need to skip nof_channels * nof_pols for every src sample
        // src is in sample/pol order (for one channel), we only need to skip nof_pols every time
        auto dst = double_buffer[producer_index].data +
                       (packet_counter - double_buffer[producer_index].sample_index) * samples * nof_pols * nof_channels +
                       channel * nof_pols;
        auto src = data_ptr;

        // For every sample (spectrum)
        for(unsigned i = 0; i < samples; i++) {
            // For every pol
            for(unsigned j = 0; j < nof_pols; j++)
                // Copy the value for the current sample/pol, for one channel, to dst
                dst[j] = src[j];

            // Advance dst and src pointers
            dst += nof_channels * nof_pols;
            src += nof_pols;
        } 
    }

    // Update number of packets
    double_buffer[producer_index].nof_packets++;

    // Update number of samples (for channel 0, assuming other channels will have a similar number, hopefully)i
    if (channel == start_channel) 
        double_buffer[producer_index].nof_samples += samples;

    // Update frequency
    if (double_buffer[producer_index].frequency > frequency)
	double_buffer[producer_index].frequency = frequency;


    // Update timings
    if (this->double_buffer[producer_index].ref_time > timestamp || double_buffer[producer_index].ref_time == 0)
        this->double_buffer[producer_index].ref_time = timestamp;
}

// Read buffer
StationRawBuffer* StationRawDoubleBuffer::read_buffer()
{
    // Wait for buffer to become available
    if (!(double_buffer[consumer].ready)) {
        nanosleep(&tim, &tim2); // Wait using nanosleep
        return nullptr;
    }

    // Lock buffer so that it's not overwritten by the producer
    double_buffer[consumer].mutex -> lock();

    return &(double_buffer[consumer]);
}

// Ready from buffer, mark as processed
void StationRawDoubleBuffer::release_buffer()
{
    // Set buffer as processed
    clear(consumer);

    // Unlock buffer
    double_buffer[consumer].mutex -> unlock();

    // Update consumer pointer
    consumer = (consumer + 1) % nof_buffers;
}

// Clear double buffer
void StationRawDoubleBuffer::clear(int index)
{
    unsigned start = 0, stop = nof_buffers;
    if (index != -1) {
        start = index;
        stop = index + 1;
    }

    // Initialise and allocate buffers in each struct instance
    for(unsigned i = start; i < stop; i++)
    {
        double_buffer[i].ref_time = DBL_MAX;
        double_buffer[i].ready = false;
        double_buffer[i].sample_index = 0;
        double_buffer[i].nof_samples = 0;
        double_buffer[i].nof_packets = 0;
        double_buffer[i].seq_number = 0;
        double_buffer[i].frequency = UINT_MAX;
        memset(double_buffer[i].data, 0, nof_samples * nof_pols * nof_channels * sizeof(uint16_t));
    }
}

// Main event loop for StationPersister
void StationRawPersister::threadEntry()
{
    // Infinite loop: Process buffers
    while (!stop_thread) {

        // Get new buffer
        StationRawBuffer *buffer;
        do {
            buffer = double_buffer->read_buffer();
            if (stop_thread)
                return;
        } while (buffer == nullptr);

        // Call callback if set
        if (callback != nullptr) {
            RawStationMetadata metadata = {buffer->frequency,
                                           buffer->nof_packets,
                                           buffer->seq_number};
            callback(buffer->data, buffer->ref_time, &metadata);
        }
        else
            LOG(INFO, "Received station beam");

        // Ready from buffer
        double_buffer->release_buffer();

        // Yield thread (for slow consumer, allow producer to overwrite buffers to keep up)
        sched_yield();
    }
}
