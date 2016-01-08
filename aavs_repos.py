import os

repos = {'aavs-backend'      : 'https://lessju@bitbucket.org/aavslmc/aavs-backend.git',
         'aavs-comms'        : 'https://lessju@bitbucket.org/aavslmc/aavs-comms.git',
         'aavs-access-layer' : 'https://lessju@bitbucket.org/aavslmc/aavs-access-layer.git',
         'aavs-logger'       : 'https://lessju@bitbucket.org/aavslmc/aavs-logger.git',
         'aavs-system'       : 'https://lessju@bitbucket.org/aavslmc/aavs-system.git',
         'aavs-filesystem'   : 'https://lessju@bitbucket.org/aavslmc/aavs-filesystem.git',
         'aavs-cluster'      : 'https://lessju@bitbucket.org/aavslmc/aavs-cluster.git' ,
         'aavs-tango'        : 'https://lessju@bitbucket.org/aavslmc/aavs-tango.git',
         'aavs-database'     : 'https://lessju@bitbucket.org/aavslmc/aavs-database.git',
         'aavs-daq'          : 'https://lessju@bitbucket.org/aavslmc/aavs-daq.git',
         'aavs-beamformer'   : 'https://lessju@bitbucket.org/aavslmc/aavs-beamformer.git',
         'aavs-calibrator'   : 'https://lessju@bitbucket.org/aavslmc/aavs-calibrator.git'}

# Script entry point
if __name__ == "__main__":
    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %aavs_repos [options]")
    parser.add_option("-c", "--clone", action="store_true", dest="clone",
                      default=False, help="Clone all repos [default: False]")
    parser.add_option("-p", "--pull", action="store_true", dest="pull",
                      default=False, help="Pull all repos [default: False]")
    parser.add_option("-l", "--list", action="store_true", dest="list",
                      default=False, help="List all repos [default: False]")
    parser.add_option("-r", "--repos", action="store", dest="repos",
                      default='all', help="Specify repos to act upton [default: all]")
    parser.add_option("-d", "--dir", action="store", dest="dir",
                      default='all', help="Specify parent directoryn [defaul: .]")
    (conf, args) = parser.parse_args(argv[1:])

    # List available repos if required
    if conf.list:
        print "\nAvailable AAVS repositories"
        print "---------------------------"
        print '\n'.join(repos.keys())
        print

    # Check if repos any repos specified
    actionable_repos = []
    if conf.repos == 'all':
        actionable_repos = repos.keys()
    else:
        for repo in conf.repos.split(','):
            if repo not in repos.keys():
                print "Invalid repository %s. Skipping" % repo
            else:
                actionable_repos.append(repo)

    if len(actionable_repos) == 0:
        print "No repositories specified. Exiting"
        exit(0)

    # We are either cloning or pulling repos. If both are specified, do nothing
    if conf.clone and conf.pull:
        print "Cannot clone and pull, please choose one of these options"

    # Change to required directory
    conf.dir = os.path.abspath(conf.dir)
    os.chdir(conf.dir)

    if conf.clone:
        for repo in actionable_repos:
            if not os.path.exists(repo):
                os.system("git clone %s" % repos[repo])
            else:
                print "Repository %s already exists. Skipping" % repo
            print
    elif conf.pull:
        for repo in actionable_repos:
            if os.path.exists(repo):
                os.chdir(os.path.join(conf.dir, repo))
                print "Pulling %s" % repo
                os.system("git pull")
                os.chdir(conf.dir)
            else:
                print "Repository %s does not exist. Skipping" % repo
            print

    print "Finished"

