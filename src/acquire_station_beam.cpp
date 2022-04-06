#include <iostream>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <cstring>
#include <cstdlib>
#include <time.h>
#include <fcntl.h>
#include <bits/stdc++.h>

//#ifndef TEST_MODE
//    #define TEST_MODE false
//#endif

#include "Utils.h"
#include "DAQ.h"

using namespace std;

// Telescope and observation parameters
float channel_bandwidth = (400e6 / 512.0) * (32 / 27.0);
string source = "UNKNOWN";
string telescope = "LFAASP";
int nbits = 8;
int npol = 2;
int ndim = 2;

int n_fine_channels = 1;

// Acqusition parameters
string base_directory = "/data/";
string interface = "eth2";
string ip = "10.0.10.40";
uint64_t nof_samples = 262144 * 4;
uint32_t start_channel = 0;
uint32_t nof_channels = 1;
uint32_t duration = 60;
uint64_t max_file_size_gb = 1;
bool simulate_write = false;

bool include_dada_header = false;
auto dada_header_size = 4096;

// File descriptor
int fd = 0;

// Callback counters
uint32_t skip = 1;
uint32_t counter = 0;
uint32_t cutoff_counter = 0;

// Callback data structure
typedef struct raw_station_metadata {
    unsigned frequency;
    unsigned nof_packets;
    unsigned buffer_counter;
} RawStationMetadata;

// Forward declarations
static std::string generate_dada_header(double timestamp, unsigned int frequency);
void allocate_space(off_t offset, size_t len);
void write_to_file(void* data);

timespec t1, t2;

void exit_with_error(const char *message) {
    // Display error message and exit with error
    perror(message);

    if (fd != -1)
        close(fd);

    exit(-1);
}


// Function to compute timing difference
float diff(timespec start, timespec end)
{
    timespec temp;
    if ((end.tv_nsec-start.tv_nsec)<0) {
        temp.tv_sec = end.tv_sec-start.tv_sec-1;
        temp.tv_nsec = 1000000000+end.tv_nsec-start.tv_nsec;
    } else {
        temp.tv_sec = end.tv_sec-start.tv_sec;
        temp.tv_nsec = end.tv_nsec-start.tv_nsec;
    }

    return temp.tv_sec + temp.tv_nsec * 1e-9;
}

// Raw station beam callback
void raw_station_beam_callback(void *data, double timestamp, void *metadata)
{
    unsigned frequency = ((RawStationMetadata *) metadata)->frequency;
    unsigned nof_packets = ((RawStationMetadata *) metadata)->nof_packets;
    unsigned buffer_counter = ((RawStationMetadata *) metadata)->buffer_counter;

    if (counter < skip) {
        counter += 1;
	    return;
    }

    unsigned long buffer_size = nof_samples * nof_channels * npol * sizeof(uint16_t);

    // Note: Assumption that first buffer in the file is not an overwritten buffer
    if ((counter - skip) % cutoff_counter == 0)
    {
        // Create output file
        std::string suffix = include_dada_header ? ".dada" : ".dat";
        std::string path = base_directory + "channel_" + std::to_string(start_channel)
                            + "_" + std::to_string(nof_channels)
                            + "_" + std::to_string(timestamp) + suffix;

        if ((fd = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_SYNC | O_DIRECT, (mode_t) 0600)) < 0)
            exit_with_error("Failed to create output data file, check directory");


        // Tell the kernel how the file is going to be accessed (sequentially) and not reused
        posix_fadvise(fd, 0, 0, POSIX_FADV_SEQUENTIAL);
        posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);

	    printf("Created file %s\n", path.c_str());

        // If required, generate DADA file and add to file
        if (include_dada_header) {
            // Define full header placeholder
            char full_header[dada_header_size];

            // Copy generated header
            auto generated_header = generate_dada_header(timestamp, frequency);
            strcpy(full_header, generated_header.c_str());

            // Fill in empty space with nulls to match required dada header size
            auto generated_header_size = generated_header.size();
            for (unsigned i = 0; i < dada_header_size - generated_header_size; i++)
                full_header[generated_header_size + i] = '\0';

            if (write(fd, full_header, dada_header_size) < 0)
                exit_with_error("Failed to generated DADA header to disk");
        }
    }

    // Determine where buffer should be written based on the buffer counter
    clock_gettime(CLOCK_REALTIME_COARSE, &t1);

    // If simulating file write, do nothing
    if (simulate_write)
        ;

    // Received expected buffer
    else if (counter == buffer_counter)
        write_to_file(data);

    // Buffer is further ahead than the current offset
    else if (buffer_counter > counter) {

        // Buffer should go in the next file. Not implemented
        if (buffer_counter % cutoff_counter < (counter - skip) % cutoff_counter)
            printf("WARNING: Cannot write buffer to future file! Skipping!\n");

        // Buffer should go ahead in current file
        else {
            // Get current position in file
            off_t current_offset = lseek(fd, 0, SEEK_CUR);

            // Allocate empty space in the file up to the beginning of the next buffer
            allocate_space(current_offset + (buffer_counter - counter) * buffer_size, buffer_size);

            // Seek to newly allocated space
            if (lseek(fd, (buffer_counter - counter) * buffer_size, SEEK_CUR) < 0)
                exit_with_error("WARNING: Cannot seek file after gap allocation. Exiting\n");

            // Write buffer
            write_to_file(data);

            // Seek back to previous position + buffer length for next buffer
            if (lseek(fd, current_offset + buffer_size, SEEK_SET) < 0)
                exit_with_error("WARNING: Cannot seek file after write to future buffer! Exiting\n");
        }
    }

    // Buffer belongs in the previous file. Not implemented
    else if (buffer_counter % cutoff_counter > (counter - skip) % cutoff_counter)
        printf("WARNING: Cannot write buffer to future file! Skipping\n");

    // Buffer belongs in the current file prior to current buffer
    else {
        // Get current position in file
        off_t current_offset = lseek(fd, 0, SEEK_CUR);

        // Go to required position in the past
        if (lseek(fd, current_offset - (counter - buffer_counter) * buffer_size, SEEK_SET) < 0)
            printf("WARNING!: Cannot seek file before current buffer! Skipping!\n");
        else {
            // Write data
            write_to_file(data);

            // Seek back to previous offset
            if (lseek(fd, current_offset + buffer_size, SEEK_SET) < 0)
                exit_with_error("Cannot seek file back to original offset. Exiting!\n");
        }
    }

    clock_gettime(CLOCK_REALTIME_COARSE, &t2);

    // Display user friendly message
    auto now = std::chrono::system_clock::now();
    auto datetime = std::chrono::system_clock::to_time_t(now);
    auto date_text = strtok(ctime(&datetime), "\n");
    cout << date_text <<  ": Written " << nof_packets << " packets in " << (unsigned) (diff(t1, t2) * 1000) << "ms" << endl;

    // Increment buffer counter
    counter++;
}

void allocate_space(off_t offset, size_t len) {
    if (fallocate(fd, FALLOC_FL_ZERO_RANGE, offset, len) < 0) {
        perror("Failed to fallocate empty gap in file");
        close(fd);
        exit(-1);
    }
}

void write_to_file(void* data) {
    // Write data buffer to disk and measure write time
    if (write(fd, data, nof_samples * nof_channels * npol * sizeof(uint16_t)) < 0) {
        perror("Failed to write buffer to disk");
        fsync(fd);
        close(fd);
        exit(-1);
    }
}

static std::string generate_dada_header(double timestamp, unsigned int frequency) {
    // Convert unix time to UTC and then to a formatted string
    const char* fmt = "%Y-%m-%d-%H:%M:%S";
    char time_string[200];
    auto t = static_cast<time_t>(timestamp);
    auto utc_time = gmtime(&t);
    strftime(time_string, sizeof(time_string), fmt, utc_time);

    // Generate DADA header
    std::stringstream header;

    // Required entries
    header << "HDR_VERSION 1.0" << endl;
    header << "HDR_SIZE " << dada_header_size << endl;
    header << "BW " << fixed << setprecision(4) << channel_bandwidth * nof_channels * 1e-6 << endl;
    header << "FREQ " << fixed << setprecision(6) << frequency * 1e-6 << endl;
    header << "TELESCOPE " << telescope << endl;
    header << "RECEIVER " << telescope << endl;
    header << "INSTRUMENT " << telescope << endl;
    header << "SOURCE " << source << endl;
    header << "MODE PSR" << endl;
    header << "NBIT " << nbits << endl;
    header << "NPOL " << npol << endl;
    header << "NCHAN " << nof_channels << endl;
    header << "NDIM " << ndim << endl;
    header << "OBS_OFFSET 0" << endl;
    header << "TSAMP " << fixed << setprecision(4) << (1.0 / channel_bandwidth) * 1e6 << endl;
    header << "UTC_START " << time_string << endl;

    // Additional entries to match post-processing requiremenents
    header << "POPULATED 1" << endl;
    header << "OBS_ID 0" << endl;
    header << "SUBOBS_ID 0" << endl;
    header << "COMMAND CAPTURE" << endl;

    header << "NTIMESAMPLES 1" << endl;
    header << "NINPUTS " << fixed << nof_channels * npol << endl;
    header << "NINPUTS_XGPU " << fixed << nof_channels * npol << endl;
    header << "METADATA_BEAMS 2" << endl;
    header << "APPLY_PATH_WEIGHTS 1" << endl;
    header << "APPLY_PATH_DELAYS 2" << endl;
    header << "INT_TIME_MSEC 0" << endl;
    header << "FSCRUNCH_FACTOR 1" << endl;
    header << "TRANSFER_SIZE 81920000" << endl;
    header << "PROJ_ID LFAASP" << endl;
    header << "EXPOSURE_SECS 8" << endl;
    header << "COARSE_CHANNEL " << nof_channels << endl;
    header << "CORR_COARSE_CHANNEL 2" << endl;
    header << "SECS_PER_SUBOBS 8" << endl;
    header << "UNIXTIME " << (int) timestamp << endl;
    header << "UNIXTIME_MSEC " << fixed << setprecision(6) << (timestamp - (int) (timestamp)) * 1e3  << endl;
    header << "FINE_CHAN_WIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth / n_fine_channels  << endl;
    header << "NFINE_CHAN " << n_fine_channels << endl;
    header << "BANDWIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth * nof_channels << endl;
    header << "SAMPLE_RATE " << fixed << setprecision(6) << channel_bandwidth << endl;
    header << "MC_IP 0" << endl;
    header << "MC_SRC_IP 0.0.0.0" << endl;
    header << "FILE_SIZE 0" << endl;
    header << "FILE_NUMBER 0" << endl;

    return header.str();
}

static void print_usage(char *name)
{
    std::cerr << "Usage: " << name << " <option(s)>\n"
              << "Options:\n"
              << "\t-d/--directory DIRECTORY \tBase directory where to store data\n"
              << "\t-t/--duration DURATION \t\tDuration to acquire in seconds\n"
              << "\t-s/--nof_samples NOF_SAMPLES\tNumber of samples\n"
              << "\t-c/--start_channel CHANNEL\tLogical channel ID to store\n"
              << "\t-n/--nof_channels NOF_CHANNELS \tNumber of channels to store from logical channel ID\n"
              << "\t-i/--interface INTERFACE\tNetwork interface to use\n"
              << "\t-p/--ip IP\t\t\tInterface IP\n"
              << "\t-m/--max_file_size\t\tMAX_FILE_SIZE in GB\n"
              << "\t-S/--source SOURCE\t\tObserved source\n"
              << "\t-D/--dada\t\t\tGenerate binary file with DADA header\n"
	      << "\t-W/--simulate\t\t\tSimualte writing to disk\n"
              << std::endl;
}

// Parse command line arguments
static void parse_arguments(int argc, char *argv[])
{
    // Define options
    const char* const short_opts = "d:t:s:i:p:c:m:n:S:D:W";
    const option long_opts[] = {
            {"directory", required_argument, nullptr, 'd'},
            {"max_file_size", required_argument, nullptr, 'm'},
            {"duration", required_argument, nullptr, 't'},
            {"nof_samples", required_argument, nullptr, 's'},
            {"start_channel", required_argument, nullptr, 'c'},
            {"nof_channels", required_argument, nullptr, 'n'},
            {"interface", required_argument, nullptr, 'i'},
            {"ip", required_argument, nullptr, 'p'},
            {"source", required_argument, nullptr, 'S'},
            {"dada", no_argument, nullptr, 'D'},
	    {"simulate", no_argument, nullptr, 'W'},
            {nullptr, no_argument, nullptr, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, short_opts, long_opts, nullptr)) != -1) {
        switch (opt) {
            case 'd': {
                    base_directory = string(optarg);
                    // Check that path end with path separator
                    auto dir_len = base_directory.length();
                    if (strncmp(base_directory.c_str() + dir_len - 1, "/", 1) != 0)
                        base_directory += '/';
                }
                break;
            case 'm':
                max_file_size_gb = atoi(optarg);
                break;
            case 't':
                duration = (uint32_t) atoi(optarg);
                break;
            case 's':
                nof_samples = (uint32_t) atoi(optarg);
                break;
            case 'c':
                start_channel = (uint32_t) atoi(optarg);
                break;
            case 'n':
                nof_channels = (uint32_t) atoi(optarg);
                break;
            case 'i':
                interface = string(optarg);
                break;
            case 'p':
                ip = string(optarg);
                break;
            case 'S':
                source = string(optarg);
                break;
            case 'D':
                include_dada_header = true;
                break;
	    case 'W':
		simulate_write = true;
		break;
            default: /* '?' */
                print_usage(argv[0]);
                exit(EXIT_FAILURE);
        }
    }

    printf("Running acquire_station_beam with %ld samples starting from logical channel %d and saving %d channels.\n",
		    nof_samples, start_channel, nof_channels);
    if (simulate_write)
	printf("Simulating disk write, nothing will be physically written to disk\n");
    else
	printf("Saving in directory %s with maximum file size of %ld GB\n", base_directory.c_str(), max_file_size_gb);
    printf("Observing source %s for %d seconds\n", source.c_str(), duration);
}

void call_station_beam_callback(uint16_t *buffer, unsigned test_counter) {
    RawStationMetadata metadata = {0,0,test_counter};
    memset(buffer, test_counter, nof_samples * nof_channels * npol * sizeof(uint16_t));
    raw_station_beam_callback(buffer, 0, &metadata);
}

void test_acquire_station_beam() {
    printf("Testing shit out\n");

    // Generate buffer for passing to callback
    uint16_t *buffer;
    allocate_aligned((void **) &buffer, PAGE_ALIGNMENT, nof_samples * nof_channels * npol * sizeof(uint16_t));

    call_station_beam_callback(buffer, 0);
    call_station_beam_callback(buffer, 1);
    call_station_beam_callback(buffer, 2);
    call_station_beam_callback(buffer, 3);
    call_station_beam_callback(buffer, 4);
    call_station_beam_callback(buffer, 5);
    call_station_beam_callback(buffer, 6);
    call_station_beam_callback(buffer, 8);
    call_station_beam_callback(buffer, 7);
    call_station_beam_callback(buffer, 10);
}

int main(int argc, char *argv[])
{
    // Process command-line argument
    parse_arguments(argc, argv);

    // Split files into max_file_size_gb x 1G. If DADA header is being generated, set do not split file (set
    // cutoff counter to "infinity"
    if (include_dada_header)
        cutoff_counter = INT_MAX;
    else
        cutoff_counter = (max_file_size_gb * 1024 * 1024 * 1024) / (nof_samples * nof_channels * npol * sizeof(uint16_t));

    // If in test mode, just call test, otherwise communicate with DAQ
    // test_acquire_station_beam();
    // exit(0);

    // Telescope information
    startReceiver(interface.c_str(), ip.c_str(), 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"start_channel", start_channel},
            {"nof_channels", nof_channels},
            {"nof_samples",     nof_samples},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "stationdataraw") != SUCCESS) {
        LOG(ERROR, "Failed to load station data conumser");
        return 0;
    }

    if (initialiseConsumer("stationdataraw", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise station data conumser");
        return 0;
    }

    if (startConsumerDynamic("stationdataraw", raw_station_beam_callback) != SUCCESS) {
        LOG(ERROR, "Failed to start station data conumser");
        return 0;
    }

    sleep(duration);

    if (stopConsumer("stationdataraw") != SUCCESS) {
        LOG(ERROR, "Failed to stop station data conumser");
        return 0;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return 0;
    }
}
