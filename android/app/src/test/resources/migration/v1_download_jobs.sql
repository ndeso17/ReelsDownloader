-- Skema v1 persis seperti yang dibuat Room sebelum kolom engine ditambahkan.
-- Dipakai test migrasi supaya titik awalnya benar-benar v1, bukan perkiraan.
CREATE TABLE IF NOT EXISTS `download_jobs` (
  `id` TEXT NOT NULL,
  `url` TEXT NOT NULL,
  `platform` TEXT NOT NULL,
  `type` TEXT NOT NULL,
  `requestedQuality` TEXT NOT NULL,
  `requestedBitrate` TEXT NOT NULL,
  `actualQuality` TEXT,
  `title` TEXT,
  `status` TEXT NOT NULL,
  `progress` INTEGER NOT NULL,
  `speed` TEXT,
  `etaSeconds` INTEGER,
  `errorName` TEXT,
  `uri` TEXT,
  `filePath` TEXT,
  `sizeBytes` INTEGER NOT NULL,
  `createdAt` INTEGER NOT NULL,
  `updatedAt` INTEGER NOT NULL,
  PRIMARY KEY(`id`)
)
