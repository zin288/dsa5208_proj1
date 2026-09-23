const hello = db.adminCommand({ hello: 1 });

if (hello.setName === "rs0") {
    print("Replica set rs0 already initialized.");
} else {
    const config = {
        _id: "rs0",

        members: [
            {
                _id: 0,
                host: "mongo1:27017",
                priority: 2,
                votes: 1,
                tags: {
                    role: "normal"
                }
            },

            {
                _id: 1,
                host: "mongo2:27018",
                priority: 1,
                votes: 1,
                tags: {
                    role: "normal"
                }
            },

            {
                _id: 2,
                host: "mongo3:27019",
                priority: 0,
                votes: 1,
                hidden: false,
                secondaryDelaySecs: 10,
                tags: {
                    role: "delayed"
                }
            }
        ],

        settings: {
            electionTimeoutMillis: 10000
        }
    };

    printjson(rs.initiate(config));
}
