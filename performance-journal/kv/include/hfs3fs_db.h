//
//  hf3fs_db.h
//  YCSB-cpp
//
//  Adapted from leveldb_db.h
//

#ifndef YCSB_C_HF3FS_DB_H_
#define YCSB_C_HF3FS_DB_H_

#include <iostream>
#include <string>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "core/db.h"
#include "utils/properties.h"

#include "hf3fs_usrbio.h"

namespace ycsbc {

class HF3FSDB : public DB {
 public:
  HF3FSDB() {}
  ~HF3FSDB() {}

  void Init();

  void Cleanup();

  Status Read(const std::string &table, const std::string &key,
              const std::vector<std::string> *fields, std::vector<Field> &result) {
    return (this->*(method_read_))(table, key, fields, result);
  }

  Status Scan(const std::string &table, const std::string &key, int len,
              const std::vector<std::string> *fields, std::vector<std::vector<Field>> &result) {
    return (this->*(method_scan_))(table, key, len, fields, result);
  }

  Status Update(const std::string &table, const std::string &key, std::vector<Field> &values) {
    return (this->*(method_update_))(table, key, values);
  }

  Status Insert(const std::string &table, const std::string &key, std::vector<Field> &values) {
    return (this->*(method_insert_))(table, key, values);
  }

  Status Delete(const std::string &table, const std::string &key) {
    return (this->*(method_delete_))(table, key);
  }

 private:
  enum StorageFormat {
    kSingleEntry,
    kRowMajor,
    kColumnMajor
  };
  StorageFormat format_;

  void SerializeRow(const std::vector<Field> &values, std::string *data);
  void DeserializeRowFilter(std::vector<Field> *values, const std::string &data,
                            const std::vector<std::string> &fields);
  void DeserializeRow(std::vector<Field> *values, const std::string &data);
  std::string BuildCompKey(const std::string &key, const std::string &field_name);
  std::string KeyFromCompKey(const std::string &comp_key);
  std::string FieldFromCompKey(const std::string &comp_key);

  Status ReadSingleEntry(const std::string &table, const std::string &key,
                         const std::vector<std::string> *fields, std::vector<Field> &result);
  Status ScanSingleEntry(const std::string &table, const std::string &key, int len,
                         const std::vector<std::string> *fields,
                         std::vector<std::vector<Field>> &result);
  Status UpdateSingleEntry(const std::string &table, const std::string &key,
                           std::vector<Field> &values);
  Status InsertSingleEntry(const std::string &table, const std::string &key,
                           std::vector<Field> &values);
  Status DeleteSingleEntry(const std::string &table, const std::string &key);

  Status ReadCompKeyRM(const std::string &table, const std::string &key,
                       const std::vector<std::string> *fields, std::vector<Field> &result);
  Status ScanCompKeyRM(const std::string &table, const std::string &key, int len,
                       const std::vector<std::string> *fields,
                       std::vector<std::vector<Field>> &result);
  Status ReadCompKeyCM(const std::string &table, const std::string &key,
                       const std::vector<std::string> *fields, std::vector<Field> &result);
  Status ScanCompKeyCM(const std::string &table, const std::string &key, int len,
                       const std::vector<std::string> *fields,
                       std::vector<std::vector<Field>> &result);
  Status InsertCompKey(const std::string &table, const std::string &key,
                       std::vector<Field> &values);
  Status DeleteCompKey(const std::string &table, const std::string &key);

  Status (HF3FSDB::*method_read_)(const std::string &, const std:: string &,
                                const std::vector<std::string> *, std::vector<Field> &);
  Status (HF3FSDB::*method_scan_)(const std::string &, const std::string &, int,
                                const std::vector<std::string> *,
                                std::vector<std::vector<Field>> &);
  Status (HF3FSDB::*method_update_)(const std::string &, const std::string &,
                                  std::vector<Field> &);
  Status (HF3FSDB::*method_insert_)(const std::string &, const std::string &,
                                  std::vector<Field> &);
  Status (HF3FSDB::*method_delete_)(const std::string &, const std::string &);

  int fieldcount_;
  std::string field_prefix_;
  std::string mount_point_;
  int io_depth_;
  int io_timeout_;
  
  struct KeyValueStore {
    std::unordered_map<std::string, std::string> data;
    std::mutex mutex;
  };
  
  static KeyValueStore kv_store_;
  static int ref_cnt_;
  static std::mutex mu_;
  
  // HF3FS related structures
  struct hf3fs_iov iov_;
  struct hf3fs_ior ior_read_;
  struct hf3fs_ior ior_write_;
  
  // Helper functions for file operations
  std::string GetFilePath(const std::string &key);
  int OpenFile(const std::string &key, bool create = false);
  Status ReadFile(const std::string &key, std::string *data);
  Status WriteFile(const std::string &key, const std::string &data);
  Status DeleteFile(const std::string &key);
};

DB *NewHF3FSDB();

} // ycsbc

#endif // YCSB_C_HF3FS_DB_H_